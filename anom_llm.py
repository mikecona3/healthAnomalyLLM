import json
import os
import statistics
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
from typing import Optional
import google.generativeai as genai

from wearable_api import HeartRateReading, StepReading, SleepReading, SpO2Reading, BloodGlucoseReading, StressScoreReading

@dataclass
class HealthRecord:
    timestamp: str
    heart_rate: float = None
    hrv: float = None
    steps: int = None 
    resting_hr: float = None 
    calories_burned: float = None
    sleep_hours: Optional[float] = None 
    spo2: Optional[float] = None
    blood_glucose: Optional[float] = None
    stress_score: Optional[float] = None 
    respiratory_rate: Optional[float] = None
    body_temperature: Optional[float] = None
    skin_temp_variation: Optional[float] = None
    ecg_rhythm: Optional[str] = None


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

    # hard bounds regardless of baselines 
    HARD_BOUNDS = {
        "heart_rate":  (30, 250),
        "hrv":         (10, 300),
        "resting_hr": (30, 150),
        "spo2":        (50, 100),
        "blood_glucose": (50, 140),
        "stress_score":(0, 100),
        "respiratory_rate": (5, 35),       
        "skin_temp_variation": (-2.0, 2.0),
        "body_temperature": (50, 120),
    }

    ECG_CONCERNING_VALUES = {"afib", "high_hr", "low_hr", "inconclusive"}

    ZSCORE_THRESHOLD = 2.5

    MIN_BASELINE_RECORDS = 7

    def __init__(self, records: list[HealthRecord]):
        self.records = records
        self._baselines = self._compute_baselines()

    def _compute_baselines(self) -> dict:
        metrics = [
            "heart_rate", "hrv", "steps", "sleep_hours",
            "spo2", "resting_hr", "calories_burned", "stress_score",
            "respiratory_rate", "skin_temp_variation", "body_temperature"
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

                # Hard bounds check
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

            anomalies += self._check_hr_spo2_combo(record, context)
            anomalies += self._check_sleep_hrv_combo(record, context)
            anomalies += self._check_respiratory_spo2_combo(record, context)
            anomalies += self._check_ecg_rhythm(record, context)

        return anomalies

    def _check_hr_spo2_combo(self, r: HealthRecord, ctx: list[dict]) -> list[Anomaly]:
        """High HR + low SpO2 together is more alarming than either alone."""
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
        """Low sleep + low HRV suggests under-recovery."""
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

    def _check_respiratory_spo2_combo(self, r: HealthRecord, ctx: list[dict]) -> list[Anomaly]:
        """Elevated respiratory rate with low SpO2 can indicate respiratory distress
        or illness onset (e.g. infection), especially if observed during sleep/rest."""
        found = []
        if r.respiratory_rate and r.spo2:
            if r.respiratory_rate > 20 and r.spo2 < 95:
                found.append(Anomaly(
                    metric="respiratory_rate+spo2",
                    value=r.respiratory_rate,
                    timestamp=r.timestamp,
                    reason=(
                        f"Elevated respiratory rate ({r.respiratory_rate} br/min) "
                        f"with reduced SpO2 ({r.spo2}%)"
                    ),
                    severity="high",
                    context_window=ctx,
                ))
        return found

    def _check_ecg_rhythm(self, r: HealthRecord, ctx: list[dict]) -> list[Anomaly]:
        """Surface device-classified rhythm flags. The watch does the signal
        classification; this just decides which classifications are worth
        escalating to the LLM for contextual interpretation."""
        found = []
        if r.ecg_rhythm and r.ecg_rhythm.lower() in self.ECG_CONCERNING_VALUES:
            rhythm = r.ecg_rhythm.lower()
            severity = "high" if rhythm == "afib" else "medium"
            found.append(Anomaly(
                metric="ecg_rhythm",
                value=rhythm,
                timestamp=r.timestamp,
                reason=f"Device classified ECG rhythm as '{rhythm}'",
                severity=severity,
                context_window=ctx,
            ))
        return found


# llm analysis 

class LLMAnalyzer:
    
    def __init__(self, model: str = "claude-sonnet-4-6"):
        self.client = anthropic.Anthropic()
        self.model = model

    def analyze(self, anomalies: list[Anomaly], user_context: str = "") -> dict:
        
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

        response = self.client.messages.create(
            model=self.model,
            max_tokens=1500,
            system=self.SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_message}]
        )

        raw = response.content[0].text.strip()
        # Strip markdown fences if the model wraps output
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        return json.loads(raw.strip())


# orchestrator

class HealthAnomalyDetector:
    
    def __init__(self, records: list[HealthRecord]):
        self.records = records
        self.screener = StatisticalScreener(records)
        self.analyzer = LLMAnalyzer()

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