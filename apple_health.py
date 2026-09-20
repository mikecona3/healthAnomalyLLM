"""
adapters/apple_health.py

Parses an Apple Health export zip and returns a list of HealthRecord objects
suitable for StatisticalScreener.

Export process on iPhone:
    Health app → profile photo → Export All Health Data → share the .zip

Individual readings (one metric, one timestamp each) are grouped into
1-hour buckets and averaged, producing one HealthRecord per hour that
had any data.  This lets the StatisticalScreener's combo rules (e.g.
HR + SpO₂ at the same time) work correctly.

HealthKit types supported
──────────────────────────
  HKQuantityTypeIdentifierHeartRate                → heart_rate      (bpm)
  HKQuantityTypeIdentifierOxygenSaturation         → spo2            (%)
  HKQuantityTypeIdentifierHeartRateVariabilitySDNN → hrv             (ms)
  HKQuantityTypeIdentifierRespiratoryRate          → respiratory_rate (br/min)
  HKQuantityTypeIdentifierBodyTemperature          → body_temperature (°C)
  HKQuantityTypeIdentifierBloodGlucose             → blood_glucose   (mg/dL)
  HKQuantityTypeIdentifierStepCount                → steps           (count)
  HKQuantityTypeIdentifierRestingHeartRate         → resting_hr      (bpm)
  HKQuantityTypeIdentifierHeartRateVariabilitySDNN → hrv             (ms)
"""

import statistics
import zipfile
import xml.etree.ElementTree as ET
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Optional, Callable

from vitals_monitor import HealthRecord


# HealthKit type identifier → HealthRecord field name
HK_TO_FIELD: dict[str, str] = {
    "HKQuantityTypeIdentifierHeartRate":                "heart_rate",
    "HKQuantityTypeIdentifierOxygenSaturation":         "spo2",
    "HKQuantityTypeIdentifierHeartRateVariabilitySDNN": "hrv",
    "HKQuantityTypeIdentifierRespiratoryRate":           "respiratory_rate",
    "HKQuantityTypeIdentifierBodyTemperature":           "body_temperature",
    "HKQuantityTypeIdentifierBloodGlucose":              "blood_glucose",
    "HKQuantityTypeIdentifierStepCount":                 "steps",
    "HKQuantityTypeIdentifierRestingHeartRate":          "resting_hr",
}

# Apple exports SpO₂ as a fraction (0.97 = 97 %) — multiply to get percent
FRACTION_FIELDS = {"spo2"}

# Body temperature above this threshold was exported in °F — convert to °C
_FAHRENHEIT_THRESHOLD = 50.0


def _parse_apple_date(date_str: str) -> datetime:
    """Parse Apple's datetime format: '2024-01-15 08:32:00 -0500'"""
    return datetime.strptime(date_str.rsplit(" ", 1)[0], "%Y-%m-%d %H:%M:%S")


def _avg(values: list) -> Optional[float]:
    return round(statistics.mean(values), 2) if values else None


def _build_health_records(
    raw: dict[str, list[tuple[float, datetime]]]
) -> list[HealthRecord]:
    """
    Group per-field readings into 1-hour buckets, averaging each metric
    within the bucket.  Returns a time-sorted list of HealthRecord objects.
    """
    # buckets[hour_ts][field] = [values]
    buckets: dict = defaultdict(lambda: defaultdict(list))

    for field, readings in raw.items():
        for value, ts in readings:
            bucket = ts.replace(minute=0, second=0, microsecond=0)
            buckets[bucket][field].append(value)

    records = []
    for bucket_ts in sorted(buckets.keys()):
        m = buckets[bucket_ts]

        def avg(f):
            return _avg(m.get(f))

        steps_vals = m.get("steps")
        steps = int(sum(steps_vals)) if steps_vals else None   # sum, not average

        records.append(HealthRecord(
            timestamp        = bucket_ts.isoformat(),
            heart_rate       = avg("heart_rate"),
            hrv              = avg("hrv"),
            resting_hr       = avg("resting_hr"),
            spo2             = avg("spo2"),
            respiratory_rate = avg("respiratory_rate"),
            body_temperature = avg("body_temperature"),
            blood_glucose    = avg("blood_glucose"),
            steps            = steps,
        ))

    return records


class AppleHealthAdapter:
    """
    Reads an Apple Health export (zip or raw xml) and returns HealthRecord objects.

    Usage:
        records, n_raw = AppleHealthAdapter("~/Downloads/export.zip").load()
        screener = StatisticalScreener(records)
    """

    def __init__(self, export_path: str | Path):
        self.path = Path(export_path).expanduser()
        if not self.path.exists():
            raise FileNotFoundError(f"Export not found: {self.path}")

    def _iter_records(self):
        """Yield <Record> XML elements from the zip or raw xml."""
        if self.path.suffix.lower() == ".zip":
            with zipfile.ZipFile(self.path) as zf:
                xml_name = next(
                    (n for n in zf.namelist() if n.endswith("export.xml")),
                    None,
                )
                if xml_name is None:
                    raise ValueError(
                        "No export.xml found inside the zip. "
                        "Make sure you used 'Export All Health Data' from the Health app."
                    )
                with zf.open(xml_name) as f:
                    for _event, elem in ET.iterparse(f, events=("end",)):
                        if elem.tag == "Record":
                            yield elem
                            elem.clear()   # keep memory low on large exports
        else:
            for _event, elem in ET.iterparse(str(self.path), events=("end",)):
                if elem.tag == "Record":
                    yield elem
                    elem.clear()

    def load(
        self,
        since: Optional[datetime] = None,
        progress_callback: Optional[Callable[[int], None]] = None,
    ) -> tuple[list[HealthRecord], int]:
        """
        Parse the export and return (records, n_raw_readings).

        Args:
            since:             Only include readings on or after this datetime.
            progress_callback: Called with (n_processed) every 10 000 records
                               — use to drive a progress bar.

        Returns:
            (list[HealthRecord], int):  hourly-bucketed records + raw reading count
        """
        raw: dict[str, list[tuple[float, datetime]]] = defaultdict(list)
        n_raw = 0

        for xml_record in self._iter_records():
            n_raw += 1
            if progress_callback and n_raw % 10_000 == 0:
                progress_callback(n_raw)

            hk_type = xml_record.get("type", "")
            field   = HK_TO_FIELD.get(hk_type)
            if field is None:
                continue

            raw_value = xml_record.get("value")
            if raw_value is None:
                continue

            try:
                value = float(raw_value)
            except ValueError:
                continue

            # Unit conversions
            if field in FRACTION_FIELDS:
                value *= 100.0                              # fraction → percent

            if field == "body_temperature" and value > _FAHRENHEIT_THRESHOLD:
                value = (value - 32) * 5 / 9               # °F → °C

            try:
                ts = _parse_apple_date(xml_record.get("startDate", ""))
            except ValueError:
                continue

            if since and ts < since:
                continue

            raw[field].append((value, ts))

        return _build_health_records(raw), n_raw
