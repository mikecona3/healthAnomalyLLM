"""
run_pipeline.py  —  CLI entry point

Runs the full two-layer pipeline from the terminal.

Examples
────────
    # Apple Health export
    python run_pipeline.py --source apple --export ~/Downloads/export.zip

    # Fitbit (run `python -m adapters.fitbit` first to authorise)
    python run_pipeline.py --source fitbit --days 7

    # Skip LLM layer (stats only, no API call)
    python run_pipeline.py --source apple --export export.zip --no-llm

    # Output raw JSON for piping into another process
    python run_pipeline.py --source apple --export export.zip --json
"""

import argparse
import json
import os
import sys

from vitals_monitor import StatisticalScreener


def main():
    parser = argparse.ArgumentParser(
        description="Health Anomaly Detector — CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--source",  choices=["apple", "fitbit"], required=True)
    parser.add_argument("--export",  help="Path to Apple Health export.zip")
    parser.add_argument("--days",    type=int, default=1,
                        help="Days of Fitbit history to pull (default: 1)")
    parser.add_argument("--no-llm",  action="store_true",
                        help="Run Layer 1 only — skip the Claude API call")
    parser.add_argument("--json",    action="store_true",
                        help="Output raw JSON (for piping)")
    parser.add_argument("--context", default="",
                        help="Optional user context sent to the LLM "
                             "(e.g. 'I ran a half-marathon yesterday')")
    args = parser.parse_args()

    # ------------------------------------------------------------------
    # Load data
    # ------------------------------------------------------------------
    if args.source == "apple":
        if not args.export:
            print("ERROR: --export path required for apple source", file=sys.stderr)
            sys.exit(1)
        from adapters.apple_health import AppleHealthAdapter
        records, n_raw = AppleHealthAdapter(args.export).load()
        if not args.json:
            print(f"Loaded {n_raw:,} raw readings  →  {len(records):,} hourly snapshots")

    elif args.source == "fitbit":
        from adapters.fitbit import FitbitAdapter
        records, n_raw = FitbitAdapter().load(days=args.days)
        if not args.json:
            print(f"Loaded {n_raw:,} readings from Fitbit ({args.days} day(s))  →  "
                  f"{len(records):,} snapshots")

    # ------------------------------------------------------------------
    # Layer 1 — Statistical screener
    # ------------------------------------------------------------------
    screener  = StatisticalScreener(records)
    anomalies = screener.screen()

    if not args.json:
        print(f"\n[Layer 1] {len(anomalies)} anomal{'y' if len(anomalies) == 1 else 'ies'} flagged\n")

    if args.no_llm or not anomalies:
        if args.json:
            print(json.dumps({
                "anomalies_found": len(anomalies),
                "anomalies": [
                    {"metric": a.metric, "value": a.value,
                     "severity": a.severity, "reason": a.reason,
                     "timestamp": a.timestamp}
                    for a in anomalies
                ]
            }, indent=2))
        else:
            for a in sorted(anomalies, key=lambda x: x.severity):
                badge = {"high": "🔴", "medium": "🟡", "low": "⚪"}.get(a.severity, "•")
                z     = f"  z={a.z_score:+.1f}σ" if a.z_score is not None else ""
                print(f"  {badge} [{a.severity.upper():6}] {a.metric:25}  "
                      f"value={a.value!s:<8}{z}")
                print(f"            {a.reason}")
                print(f"            @ {a.timestamp[:16]}\n")

            if not anomalies:
                print("  ✅  No anomalies detected.")
        return

    # ------------------------------------------------------------------
    # Layer 2 — LLM interpretation
    # ------------------------------------------------------------------
    if not os.getenv("ANTHROPIC_API_KEY"):
        print("WARNING: ANTHROPIC_API_KEY not set — skipping LLM layer.",
              file=sys.stderr)
        sys.exit(1)

    from health_anomaly_detector import LLMAnalyzer
    print(f"[Layer 2] Sending {len(anomalies)} anomalies to Claude...")
    result = LLMAnalyzer().analyze(anomalies, user_context=args.context)

    if args.json:
        print(json.dumps(result, indent=2))
        return

    print(f"\n── Overall Summary ─────────────────────────────")
    print(result.get("overall_summary", ""))

    patterns = result.get("patterns_detected", [])
    if patterns:
        print(f"\n── Patterns Detected ───────────────────────────")
        for p in patterns:
            print(f"  • {p}")

    print(f"\n── Anomaly Assessments ─────────────────────────")
    for a in result.get("anomaly_assessments", []):
        print(f"\n  {a.get('metric')}  @  {a.get('timestamp','')[:16]}")
        print(f"  {a.get('plain_english')}")
        print(f"  Causes : {', '.join(a.get('possible_causes', []))}")
        print(f"  Action : {a.get('recommendation')}  [{a.get('urgency','').upper()}]")

    print("\n⚠  This is not medical advice.")


if __name__ == "__main__":
    main()
