"""
health_anomaly_detector.py  —  Layer 2: LLM Interpretation

Takes the list[Anomaly] from StatisticalScreener and sends them to the
Claude API for contextual, plain-English interpretation.

Fixed from anom_llm.py:
  • Removed `import google.generativeai as genai`  (wrong import, unused)
  • Removed `from wearable_api import ...`          (non-existent; replaced by adapters/)
  • Added `import anthropic`                        (was used but never imported)
  • Added SYSTEM_PROMPT                             (was referenced but never defined)
  • LLMAnalyzer now reads ANTHROPIC_API_KEY from env automatically via the SDK
"""

import anthropic
import json
from dataclasses import asdict

from vitals_monitor import HealthRecord, Anomaly, StatisticalScreener


# ---------------------------------------------------------------------------
# Layer 2 — LLM Analyzer
# ---------------------------------------------------------------------------

class LLMAnalyzer:
    """
    Sends flagged anomalies to the Claude API for contextual interpretation.
    Only called when StatisticalScreener has found at least one anomaly,
    keeping API costs minimal.

    Requires ANTHROPIC_API_KEY environment variable to be set.
    """

    SYSTEM_PROMPT = """You are a health data analyst reviewing statistical anomalies \
flagged in a person's wearable device data.

You will receive a JSON payload describing one or more anomalies. For each one, provide:
  • A plain-English explanation of what the reading means
  • Likely causes — benign explanations first, concerning ones second
  • A clear recommended action

Rules:
  - You are NOT a medical professional. Never diagnose. Frame everything as observations.
  - Always recommend consulting a doctor for anything high-severity.
  - Be concise and reassuring where appropriate — most anomalies have benign causes.

Respond ONLY with valid JSON — no markdown fences, no preamble, no trailing text.
Use exactly this structure:

{
  "anomaly_assessments": [
    {
      "metric": "string",
      "timestamp": "string",
      "plain_english": "One clear sentence explaining what this reading means",
      "possible_causes": ["Most likely benign cause", "Less likely concerning cause"],
      "recommendation": "What the person should do about this",
      "urgency": "low | medium | high"
    }
  ],
  "overall_summary": "2–3 sentence summary of the overall pattern across all anomalies",
  "patterns_detected": ["Pattern 1 if any", "Pattern 2 if any"]
}"""

    def __init__(self, model: str = "claude-sonnet-4-6"):
        # Reads ANTHROPIC_API_KEY from environment automatically
        self.client = anthropic.Anthropic()
        self.model  = model

    def analyze(self, anomalies: list, user_context: str = "") -> dict:
        """
        Send anomalies to the LLM and return its structured interpretation.

        Args:
            anomalies:    list[Anomaly] from StatisticalScreener.screen()
            user_context: Optional free-text the user provides about themselves
                          (e.g. "I went on a long run yesterday")

        Returns:
            dict with keys: anomaly_assessments, overall_summary, patterns_detected
        """
        if not anomalies:
            return {
                "anomaly_assessments": [],
                "overall_summary":     "No anomalies detected in this dataset.",
                "patterns_detected":   [],
            }

        payload = {
            "user_context": user_context or "No additional context provided.",
            "anomalies": [
                {
                    "timestamp":          a.timestamp,
                    "metric":             a.metric,
                    "value":              a.value,
                    "statistical_reason": a.reason,
                    "severity":           a.severity,
                    "context_window":     a.context_window,
                }
                for a in anomalies
            ],
        }

        response = self.client.messages.create(
            model=self.model,
            max_tokens=2000,
            system=self.SYSTEM_PROMPT,
            messages=[
                {
                    "role":    "user",
                    "content": (
                        "Please analyze the following health anomalies:\n\n"
                        f"```json\n{json.dumps(payload, indent=2)}\n```"
                    ),
                }
            ],
        )

        raw = response.content[0].text.strip()
        # Strip accidental markdown fences (shouldn't happen with explicit prompt)
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        return json.loads(raw.strip())


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

class HealthAnomalyDetector:
    """
    Full two-layer pipeline orchestrator.

      Layer 1 → StatisticalScreener  (fast, free, runs first)
      Layer 2 → LLMAnalyzer          (Claude API — only runs if anomalies found)

    Usage (CLI / scripting):
        from adapters.apple_health import AppleHealthAdapter
        from health_anomaly_detector import HealthAnomalyDetector

        records, _ = AppleHealthAdapter("export.zip").load()
        result      = HealthAnomalyDetector(records).run()
        print(result["overall_summary"])

    The GUI calls Layer 1 and Layer 2 separately so it can show stat results
    immediately and defer the LLM call to a button press.
    """

    def __init__(self, records: list):
        self.records  = records
        self.screener = StatisticalScreener(records)
        self.analyzer = LLMAnalyzer()

    def run(self, user_context: str = "") -> dict:
        print(f"[Layer 1] Screening {len(self.records)} records...")
        anomalies = self.screener.screen()
        print(f"[Layer 1] {len(anomalies)} anomal{'y' if len(anomalies) == 1 else 'ies'} flagged.")

        if not anomalies:
            return {
                "anomalies_found":     0,
                "overall_summary":     "No anomalies detected. All readings within normal range.",
                "patterns_detected":   [],
                "anomaly_assessments": [],
                "raw_anomalies":       [],
            }

        print(f"[Layer 2] Sending {len(anomalies)} anomalies to Claude...")
        llm_result = self.analyzer.analyze(anomalies, user_context)

        return {
            "anomalies_found": len(anomalies),
            "raw_anomalies":   [asdict(a) for a in anomalies],
            **llm_result,
        }
