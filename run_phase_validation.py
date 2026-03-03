#!/usr/bin/env python3
"""
Store & Booking Validation Runner.

Executes vla_unified_agent.py with the Store/Booking scenario file,
then parses the run output to produce a structured validation report
with per-scenario diagnostics and aggregate statistics.

Usage:
    python run_phase_validation.py
"""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
AGENT_SCRIPT = SCRIPT_DIR / "vla_unified_agent.py"
SCENARIO_FILE = SCRIPT_DIR / "test_scenarios_phase_store_booking.json"
RUNS_DIR = SCRIPT_DIR / "runs"
PYTHON = SCRIPT_DIR / ".venv" / "bin" / "python"

if not PYTHON.exists():
    PYTHON = Path(sys.executable)


def find_newest_run():
    """Find the most recently created run directory."""
    if not RUNS_DIR.exists():
        return None
    dirs = sorted(
        [d for d in RUNS_DIR.iterdir() if d.is_dir()],
        key=lambda d: d.stat().st_mtime,
        reverse=True,
    )
    return dirs[0] if dirs else None


def load_json(path):
    with open(path) as f:
        return json.load(f)


def analyze_trace(trace_data):
    """Extract metrics from a single trace JSON."""
    steps = trace_data.get("steps", [])
    scenario = trace_data.get("scenario", {})

    type_actions = sum(1 for s in steps if s.get("action_type") == "TYPE")
    click_actions = sum(1 for s in steps if s.get("action_type") == "CLICK")
    fallback_count = sum(1 for s in steps if s.get("fallback"))

    latencies = [s["llm_latency"] for s in steps
                 if "llm_latency" in s and isinstance(s["llm_latency"], (int, float))]
    avg_latency = sum(latencies) / max(len(latencies), 1) if latencies else 0.0

    # Detect same-URL loop
    urls = [s.get("url", "") for s in steps]
    loop_triggered = False
    if len(urls) >= 6:
        for i in range(len(urls) - 5):
            if len(set(urls[i:i+6])) == 1:
                loop_triggered = True
                break

    # Last 3 actions (for failure diagnostics)
    last_actions = []
    for s in steps[-3:]:
        last_actions.append({
            "step": s.get("step"),
            "action": s.get("action_desc", "?"),
            "url": s.get("url", "?")[:70],
        })

    return {
        "type_actions": type_actions,
        "click_actions": click_actions,
        "fallback_count": fallback_count,
        "avg_latency": round(avg_latency, 2),
        "loop_triggered": loop_triggered,
        "total_steps_traced": len(steps),
        "last_3_actions": last_actions,
    }


def print_divider(char="═", width=60):
    print(char * width)


def print_scenario_report(idx, scenario_summary, trace_metrics):
    """Print a formatted report block for one scenario."""
    print()
    print(f"  Scenario {idx}: {scenario_summary.get('name', '?')}")
    print(f"  {'─' * 56}")

    success = scenario_summary.get("success", False)
    steps = scenario_summary.get("steps_taken", 0)
    final_url = scenario_summary.get("final_url", "")
    reason = scenario_summary.get("reason", "")
    keyword = scenario_summary.get("keyword", "")

    status = "✅ Yes" if success else "❌ No"
    print(f"  Success:                   {status}")
    print(f"  Steps:                     {steps}")
    print(f"  Final URL:                 {final_url[:70]}")
    print(f"  TYPE actions:              {trace_metrics['type_actions']}")
    print(f"  CLICK actions:             {trace_metrics['click_actions']}")
    print(f"  Fallback actions:          {trace_metrics['fallback_count']}")
    print(f"  Loop triggered:            {'Yes' if trace_metrics['loop_triggered'] else 'No'}")
    print(f"  Avg LLM latency:           {trace_metrics['avg_latency']}s")

    kw_detected = "Yes" if (success and keyword and keyword.lower()
                            in reason.lower()) else "No"
    if success and "marker" in reason.lower():
        kw_detected = "Yes (success marker)"
    if success and "keyword" in reason.lower():
        kw_detected = "Yes"
    print(f"  Completion marker detected: {kw_detected}")
    print(f"  Reason:                    {reason[:60]}")


def main():
    print()
    print_divider()
    print("  STORE & BOOKING VALIDATION")
    print_divider()
    print()

    # ── Step 1: Verify prerequisites ──
    if not AGENT_SCRIPT.exists():
        print(f"  ❌ Agent not found: {AGENT_SCRIPT}")
        sys.exit(1)
    if not SCENARIO_FILE.exists():
        print(f"  ❌ Scenario file not found: {SCENARIO_FILE}")
        sys.exit(1)

    scenarios = load_json(SCENARIO_FILE)
    print(f"  Scenarios: {len(scenarios)}")
    for i, s in enumerate(scenarios, 1):
        print(f"    {i}. {s['name']}")
    print()

    # ── Step 2: Run the unified agent ──
    print("  ▶ Running vla_unified_agent.py ...")
    print(f"    Command: {PYTHON} {AGENT_SCRIPT} --scenarios {SCENARIO_FILE}")
    print()

    t0 = time.time()
    result = subprocess.run(
        [str(PYTHON), str(AGENT_SCRIPT),
         "--scenarios", str(SCENARIO_FILE)],
        cwd=str(SCRIPT_DIR),
        capture_output=False,
        text=True,
    )
    elapsed = time.time() - t0

    print()
    print(f"  Agent finished in {elapsed:.1f}s  (exit code: {result.returncode})")
    print()

    # ── Step 3: Find newest run and load results ──
    run_dir = find_newest_run()
    if not run_dir:
        print("  ❌ No run directory found under runs/")
        sys.exit(1)

    print(f"  📁 Run dir: {run_dir}")

    summary_path = run_dir / "summary.json"
    if not summary_path.exists():
        print("  ❌ summary.json not found in run directory")
        sys.exit(1)

    summaries = load_json(summary_path)
    print(f"  📄 Loaded {len(summaries)} scenario results")

    # Load trace files
    trace_files = sorted(run_dir.glob("trace_*.json"))
    traces = {}
    for tf in trace_files:
        data = load_json(tf)
        name = data.get("scenario", {}).get("name", tf.stem)
        traces[name] = data

    # ── Step 4: Generate report ──
    print()
    print_divider()
    print("  VALIDATION REPORT")
    print_divider()

    all_metrics = []
    for idx, sc_summary in enumerate(summaries, 1):
        name = sc_summary.get("name", f"Scenario {idx}")
        trace_data = traces.get(name, {"steps": [], "scenario": sc_summary})
        metrics = analyze_trace(trace_data)
        all_metrics.append((sc_summary, metrics))
        print_scenario_report(idx, sc_summary, metrics)

    # ── Step 5: Aggregate statistics ──
    print()
    print_divider("─")
    print("  AGGREGATE STATISTICS")
    print_divider("─")

    total = len(all_metrics)
    successes = sum(1 for s, _ in all_metrics if s.get("success"))
    failures = total - successes

    success_steps = [s["steps_taken"] for s, _ in all_metrics if s.get("success")]
    avg_success_steps = (sum(success_steps) / len(success_steps)
                         if success_steps else 0)

    all_types = [m["type_actions"] for _, m in all_metrics]
    all_clicks = [m["click_actions"] for _, m in all_metrics]
    all_fallbacks = [m["fallback_count"] for _, m in all_metrics]
    all_latencies = [m["avg_latency"] for _, m in all_metrics if m["avg_latency"] > 0]
    loops = sum(1 for _, m in all_metrics if m["loop_triggered"])

    print(f"\n  Overall success rate:      {successes}/{total} "
          f"({successes/max(total,1)*100:.0f}%)")
    print(f"  Avg steps (successful):    {avg_success_steps:.1f}")
    print(f"  Avg TYPE actions/scenario: {sum(all_types)/max(total,1):.1f}")
    print(f"  Avg CLICK actions/scenario:{sum(all_clicks)/max(total,1):.1f}")
    print(f"  Avg fallback/scenario:     {sum(all_fallbacks)/max(total,1):.1f}")
    print(f"  Avg LLM latency:           "
          f"{sum(all_latencies)/max(len(all_latencies),1):.2f}s")
    print(f"  Same-URL loops triggered:  {loops}")

    # ── Step 6: Failure diagnostics ──
    if failures > 0:
        print()
        print_divider("─")
        print("  FAILURE DIAGNOSTICS")
        print_divider("─")

        for sc, metrics in all_metrics:
            if not sc.get("success"):
                print(f"\n  ❌ {sc.get('name', '?')}")
                print(f"     Reason: {sc.get('reason', '?')}")
                print(f"     Final URL: {sc.get('final_url', '?')[:70]}")
                print(f"     Last 3 actions:")
                for a in metrics["last_3_actions"]:
                    print(f"       Step {a['step']}: {a['action'][:60]}")
                    print(f"                URL: {a['url']}")
    else:
        print()
        print("  🎉 No failures — all scenarios passed!")

    # ── Step 7: Domain breakdown ──
    print()
    print_divider("─")
    print("  DOMAIN BREAKDOWN")
    print_divider("─")

    store_results = [(s, m) for s, m in all_metrics
                     if s.get("domain") == "store"]
    booking_results = [(s, m) for s, m in all_metrics
                       if s.get("domain") == "booking"]

    for domain_name, domain_data in [("Store", store_results),
                                      ("Booking", booking_results)]:
        d_total = len(domain_data)
        d_ok = sum(1 for s, _ in domain_data if s.get("success"))
        d_types = sum(m["type_actions"] for _, m in domain_data)
        d_clicks = sum(m["click_actions"] for _, m in domain_data)
        d_loops = sum(1 for _, m in domain_data if m["loop_triggered"])
        print(f"\n  {domain_name}:")
        print(f"    Scenarios:    {d_total}")
        print(f"    Success:      {d_ok}/{d_total}")
        print(f"    Total TYPEs:  {d_types}")
        print(f"    Total CLICKs: {d_clicks}")
        print(f"    Loops:        {d_loops}")

    print()
    print_divider()
    print("  VALIDATION COMPLETE")
    print_divider()
    print()


if __name__ == "__main__":
    main()
