# 🫀 Health Anomaly Detector

A two-layer anomaly detection pipeline over Apple Health and Fitbit wearable data.
Layer 1 runs a fast statistical pre-screen to catch genuine anomalies without wasting
API tokens. Layer 2 sends only the flagged readings to Claude for plain-English
interpretation.

---

## Architecture

```
Apple Health export.zip          Fitbit REST API
        │                               │
        ▼                               ▼
 adapters/apple_health.py     adapters/fitbit.py
        │                               │
        └──────────┬────────────────────┘
                   │  list[HealthRecord]
                   ▼
          vitals_monitor.py
          StatisticalScreener
          ┌─────────────────────────────┐
          │ 1. Hard physiological bounds│  ← catches acute events
          │ 2. Personal z-score         │  ← catches "unusual for YOU"
          │ 3. Multi-metric combo rules │  ← HR+SpO₂, sleep+HRV, etc.
          └─────────────────────────────┘
                   │  list[Anomaly]  (only if anomalies found)
                   ▼
       health_anomaly_detector.py
            LLMAnalyzer  →  Claude API
                   │
                   ▼
          Plain-English interpretation
          per anomaly + overall summary
```

---

## File Structure

```
health-anomaly-detector/
│
├── gui.py                      # macOS GUI — drag & drop + results table + AI button
├── vitals_monitor.py           # HealthRecord, Anomaly, StatisticalScreener (Layer 1)
├── health_anomaly_detector.py  # LLMAnalyzer, HealthAnomalyDetector (Layer 2)
├── run_pipeline.py             # CLI entry point
├── requirements.txt
├── README.md
│
└── adapters/
    ├── __init__.py
    ├── apple_health.py         # Parses Apple Health export.zip → list[HealthRecord]
    └── fitbit.py               # Fitbit REST API → list[HealthRecord]
```

---

## Setup

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Set your Anthropic API key

```bash
export ANTHROPIC_API_KEY="sk-ant-..."
```

Add it to your `~/.zshrc` or `~/.bash_profile` to make it permanent.

---

## Usage

### GUI (recommended)

```bash
python gui.py
```

Then on your iPhone:
> **Health app → Profile photo → Export All Health Data**

AirDrop or cable-transfer the `export.zip` to your Mac, then drag it onto
the drop zone in the app.

**What happens:**
1. The export is parsed in the background (large files show progress in the status bar)
2. Layer 1 results appear immediately in the colour-coded table
   - 🔴 **HIGH** — outside hard physiological bounds or >3.5 SD from your baseline
   - 🟡 **MEDIUM** — between 2.5–3.5 SD from your baseline
3. Click **🤖 Analyze with AI** to send flagged anomalies to Claude
4. Claude's plain-English interpretation appears in the panel below

### CLI

```bash
# Apple Health export — stats only (no API call)
python run_pipeline.py --source apple --export ~/Downloads/export.zip --no-llm

# Apple Health export — full pipeline with LLM
python run_pipeline.py --source apple --export ~/Downloads/export.zip

# With user context (helps the LLM interpret anomalies)
python run_pipeline.py --source apple --export export.zip \
    --context "I ran a half-marathon on Saturday"

# Fitbit — last 7 days
python run_pipeline.py --source fitbit --days 7

# Output raw JSON for piping
python run_pipeline.py --source apple --export export.zip --json
```

### Fitbit one-time OAuth setup

```bash
export FITBIT_CLIENT_ID="your_id"
export FITBIT_CLIENT_SECRET="your_secret"
python -m adapters.fitbit      # opens browser, saves token to .fitbit_token
```

Get credentials at [dev.fitbit.com](https://dev.fitbit.com) → Create App → Personal.

---

## Metrics Tracked

| Metric | Source | Hard Bounds |
|---|---|---|
| Heart rate | Apple Health / Fitbit | 40–220 bpm |
| HRV (SDNN/RMSSD) | Apple Health | 0–300 ms |
| SpO₂ | Apple Health / Fitbit | 80–100 % |
| Respiratory rate | Apple Health / Fitbit | 5–35 br/min |
| Body temperature | Apple Health / Fitbit | 35–41 °C |
| Blood glucose | Apple Health | 50–400 mg/dL |
| Resting heart rate | Apple Health | 30–150 bpm |
| Steps | Apple Health | — |
| ECG rhythm | Apple Health | afib / high_hr / low_hr |

### Multi-metric combo rules

| Rule | Condition | Severity |
|---|---|---|
| HR + SpO₂ | HR > 110 bpm AND SpO₂ < 94% | High |
| Sleep + HRV | Sleep < 5 h AND HRV < 20 ms | Medium |
| RR + SpO₂ | Resp rate > 20 AND SpO₂ < 95% | High |
| ECG rhythm | Device flags afib / inconclusive | High / Medium |

---

## How data flows from Apple Health

Apple Health does **not** have a public REST API. The only way to get data
into a Python pipeline is the manual export:

```
iPhone Health app → Profile photo → Export All Health Data
```

This produces `export.zip` containing `export.xml` with every recorded metric.
The adapter parses this file, groups individual readings into 1-hour buckets,
and averages each metric within each bucket to produce `HealthRecord` objects.

For **live/automatic** Apple Health data, a small HealthKit companion app in
Swift would POST readings to a local HTTP endpoint — this is planned for a
future release.

---

## Notes

- **ANTHROPIC_API_KEY** must be set for the LLM layer. Layer 1 (stats) works without it.
- **Google Fit API** was shut down June 2025. Fitbit is the recommended Android source.
- **Health Connect** (Android) is SDK-only with no REST API — requires an Android companion app.
- This tool is **not a medical device** and does not provide medical diagnoses.
  Always consult a healthcare professional for anything concerning.
