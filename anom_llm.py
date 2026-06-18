import json
import os
import statistics
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
from typing import Optional
import google.generativeai as genai



@dataclass
class HealthRecord:
    timestamp: str
    heart_rate: Optional[float] = None
    hrv: Optional[float] = None
    steps: Optional[int] = None 
    sleep_hours: Optional[float] = None 
    spo2: Optional[float] = None 
    resting_hr: Optional[float] = None 
    calories_burned: Optional[float] = None
    stress_score: Optional[float] = None 


@dataclass
class Anomaly:
    metric: str
    value: float
    timestamp: str
    reason: str                  # flag from Layer 1
    severity: str                # rated as low, medium or high
    context_window: list[dict]   # surrounding records for LLM


# pre-screen 

class StatisticalScreener:
    # run 1st to save API calls/tokens  

    # Hard bounds regardless of baselines 
    HARD_BOUNDS = {
        "heart_rate":  (30, 250),
        "spo2":        (50, 100),
        "hrv":         (10, 300),
        "stress_score":(0, 100),
    }

    # measurement of deviations
    ZSCORE_THRESHOLD = 2.5

    # records to complete a personal baseline for z-score calculations
    MIN_BASELINE_RECORDS = 7

    def __init__(self, records: list[HealthRecord]):
        self.records = records
        self._baselines = self._compute_baselines()

    def _compute_baselines(self) -> dict:
        metrics = [
            "heart_rate", "hrv", "steps", "sleep_hours",
            "spo2", "resting_hr", "calories_burned", "stress_score"
        ]
        baselines = {}
        for m in metrics:
            values = [getattr(r, m) for r in self.records if getattr(r, m) is not None]
            if len(values) >= self.MIN_BASELINE_RECORDS:
                baselines[m] = {
                    "mean": statistics.mean(values),
                    "stdev": statistics.stdev(values) or 0.01,  # avoid div/0
                    "min": min(values),
                    "max": max(values),
                    "count": len(values),
                }
        return baselines

    def _zscore(self, metric: str, value: float) -> Optional[float]:
        if metric not in self._baselines:
            return None
        b = self._baselines[metric]
        return abs(value - b["mean"]) / b["stdev"]

    def screen(self) -> list[Anomaly]:
        anomalies = []
        records_as_dicts = [asdict(r) for r in self.records]

        for i, record in enumerate(self.records):
            # Context window: up to 3 records before and after
            window_start = max(0, i - 3)
            window_end = min(len(self.records), i + 4)
            context = records_as_dicts[window_start:window_end]

            for metric, (lo, hi) in self.HARD_BOUNDS.items():
                value = getattr(record, metric)
                if value is None:
                    continue

                # hard bounds check
                if not (lo <= value <= hi):
                    anomalies.append(Anomaly(
                        metric=metric,
                        value=value,
                        timestamp=record.timestamp,
                        reason=f"Outside safe range [{lo}, {hi}]",
                        severity="high",
                        context_window=context,
                    ))
                    continue

                # checks deviations from personal baseline
                z = self._zscore(metric, value)
                if z is not None and z >= self.ZSCORE_THRESHOLD:
                    b = self._baselines[metric]
                    severity = "high" if z > 3.5 else "medium"
                    anomalies.append(Anomaly(
                        metric=metric,
                        value=value,
                        timestamp=record.timestamp,
                        reason=(
                            f"Z-score {z:.1f}σ from personal mean "
                            f"(mean={b['mean']:.1f}, stdev={b['stdev']:.1f})"
                        ),
                        severity=severity,
                        context_window=context,
                    ))

            # custom multi-metric rules
            anomalies += self._check_hr_spo2_combo(record, context)
            anomalies += self._check_sleep_hrv_combo(record, context)

        return anomalies

    def _check_hr_spo2_combo(self, r: HealthRecord, ctx: list[dict]) -> list[Anomaly]:
        # check for high hr + low spo2 combo 
        found = []
        if r.heart_rate and r.spo2:
            if r.heart_rate > 110 and r.spo2 < 94:
                found.append(Anomaly(
                    metric="heart_rate+spo2",
                    value=r.heart_rate,
                    timestamp=r.timestamp,
                    reason=f"Elevated HR ({r.heart_rate} bpm) with low SpO2 ({r.spo2}%)",
                    severity="high",
                    context_window=ctx,
                ))
        return found

    def _check_sleep_hrv_combo(self, r: HealthRecord, ctx: list[dict]) -> list[Anomaly]:
        # check for low sleep values + low HRV combo
        found = []
        if r.sleep_hours and r.hrv:
            if r.sleep_hours < 5 and r.hrv < 20:
                found.append(Anomaly(
                    metric="sleep+hrv",
                    value=r.sleep_hours,
                    timestamp=r.timestamp,
                    reason=f"Poor sleep ({r.sleep_hours}h) with very low HRV ({r.hrv} ms)",
                    severity="medium",
                    context_window=ctx,
                ))
        return found


# LLM analysis

class LLMAnalyzer:
    # sends flagged anomalies to gemini, batches multiples together to reduce API/tokens 

    def __init__(self, model: str = "gemini-1.5-flash"):
        api_key = os.environ.get("GOOGLE_API_KEY")
        if not api_key:
            raise ValueError(
                "GOOGLE_API_KEY environment variable not set. "
                "Please run: export GOOGLE_API_KEY='your-api-key'")
        genai.configure(api_key=os.environ.get("GOOGLE_API_KEY"))
        self.model = model
        self.client = genai.GenerativeModel(
            model_name=self.model,
            system_instruction=self.SYSTEM_PROMPT
        )

    def analyze(self, anomalies: list[Anomaly], user_context: str = "") -> dict:
        """
        Send a batch of anomalies to the LLM for analysis.

        Args:
            anomalies: Flagged anomalies from Layer 1
            user_context: Optional free-text about the user
                          (e.g. "42-year-old recreational runner, no known conditions")
        """
        if not anomalies:
            return {
                "anomaly_assessments": [],
                "overall_summary": "No anomalies detected in this dataset.",
                "patterns_detected": []
            }

        payload = {
            "user_context": user_context or "No user context provided.",
            "anomalies": [
                {
                    "timestamp": a.timestamp,
                    "metric": a.metric,
                    "value": a.value,
                    "statistical_reason": a.reason,
                    "severity": a.severity,
                    "context_window": a.context_window,
                }
                for a in anomalies
            ]
        }

        user_message = (
            f"Please analyze the following health data anomalies:\n\n"
            f"```json\n{json.dumps(payload, indent=2)}\n```"
        )

        response = self.client.generate_content(
            user_message,
            generation_config=genai.GenerationConfig(
                response_mime_type="application/json",
                max_output_tokens=1500,
            )
        )

        return json.loads(response.text)


# orchestrator

class HealthAnomalyDetector:
    # combines layer data and returns report 
    
    """
    Usage:
        detector = HealthAnomalyDetector(records)
        report = detector.run(user_context="35yo male, trains 5x/week")
        print(report["overall_summary"])
    """

    def __init__(self, records: list[HealthRecord], model: str = "gemini-1.5-flash"):
        self.records = records
        self.screener = StatisticalScreener(records)
        self.analyzer = LLMAnalyzer(model=model)

    def run(self, user_context: str = "") -> dict:
        print(f"[Layer 1] Screening {len(self.records)} records...")
        anomalies = self.screener.screen()
        print(f"[Layer 1] Found {len(anomalies)} statistical anomalies.")

        if not anomalies:
            return {
                "anomalies_found": 0,
                "overall_summary": "No anomalies detected. Data looks normal.",
                "patterns_detected": [],
                "anomaly_assessments": [],
            }

        print(f"[Layer 2] Sending {len(anomalies)} anomalies to LLM...")
        llm_result = self.analyzer.analyze(anomalies, user_context)

        return {
            "anomalies_found": len(anomalies),
            "raw_anomalies": [asdict(a) for a in anomalies],
            **llm_result,
        }


# internal test - not included in final release 

def _generate_sample_data() -> list[HealthRecord]:
    """Generate 14 days of plausible health data with a few planted anomalies."""
    import random
    random.seed(42)
    records = []
    base = datetime(2026, 6, 1, 7, 0, 0)

    for day in range(14):
        dt = base + timedelta(days=day)
        hr = random.gauss(68, 6)
        hrv = random.gauss(55, 10)
        spo2 = random.gauss(97.5, 0.8)
        sleep = random.gauss(7.2, 0.7)

        # anomaly 1 - high HR + low SpO2
        if day == 10:
            hr = 150
            spo2 = 81

        # anomaly 2 - very low HRV + poor sleep
        if day == 12:
            hrv = 12
            sleep = 1.0

        records.append(HealthRecord(
            timestamp=dt.isoformat(),
            heart_rate=round(hr, 1),
            hrv=round(hrv, 1),
            spo2=round(min(spo2, 100), 1),
            sleep_hours=round(max(sleep, 0), 1),
            steps=random.randint(4000, 12000),
            resting_hr=round(random.gauss(58, 4), 1),
            stress_score=round(random.gauss(35, 15), 1),
        ))

    return records


if __name__ == "__main__":
    records = _generate_sample_data()
    detector = HealthAnomalyDetector(records)
    report = detector.run(user_context="34-year-old recreational runner, no known conditions")

    print("\n" + "=" * 60)
    print(f"Anomalies found: {report['anomalies_found']}")
    print(f"\nSummary: {report['overall_summary']}")

    if report.get("patterns_detected"):
        print(f"\nPatterns: {', '.join(report['patterns_detected'])}")

    print("\nDetailed assessments:")
    for a in report.get("anomaly_assessments", []):
        print(f"  [{a['concern_level'].upper()}] {a['timestamp']} — {a['metric']}")
        print(f"    Likely cause: {a['likely_cause']}")
        if a.get("notes"):
            print(f"    Notes: {a['notes']}")