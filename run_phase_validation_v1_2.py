#!/usr/bin/env python3
"""
Validation Runner for v1.2 — Runs Store/Booking scenarios and produces
comparison report against v1.1 baseline.

Usage:
    python run_phase_validation_v1_2.py
"""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
AGENT = SCRIPT_DIR / "vla_unified_agent_v1_2.py"
SCENARIOS = SCRIPT_DIR / "test_scenarios_phase_store_booking.json"
RUNS_DIR = SCRIPT_DIR / "runs"
REPORTS_DIR = SCRIPT_DIR / "reports_unified_v1_2"
PYTHON = SCRIPT_DIR / ".venv" / "bin" / "python"
if not PYTHON.exists():
    PYTHON = Path(sys.executable)

# v1.1 baseline from previous run
V11_BASELINE = [
    {"name": "Store — Single Item Purchase", "success": True, "steps_taken": 8,
     "type_actions": 4, "click_actions": 4, "avg_latency": 1.5, "loop": False,
     "adherence": "N/A"},
    {"name": "Store — Multi Item Purchase", "success": False, "steps_taken": 30,
     "type_actions": 16, "click_actions": 14, "avg_latency": 1.1, "loop": False,
     "adherence": "N/A"},
    {"name": "Booking — Hotel Reservation", "success": False, "steps_taken": 4,
     "type_actions": 0, "click_actions": 3, "avg_latency": 1.0, "loop": False,
     "adherence": "N/A"},
    {"name": "Booking — Doctor Appointment", "success": False, "steps_taken": 14,
     "type_actions": 8, "click_actions": 2, "avg_latency": 1.2, "loop": True,
     "adherence": "N/A"},
]


def newest_run():
    if not RUNS_DIR.exists(): return None
    dirs = sorted([d for d in RUNS_DIR.iterdir() if d.is_dir()],
                  key=lambda d: d.stat().st_mtime, reverse=True)
    return dirs[0] if dirs else None


def analyze_trace(data):
    steps = data.get("steps", [])
    types = sum(1 for s in steps if s.get("action_type") == "TYPE")
    clicks = sum(1 for s in steps if s.get("action_type") == "CLICK")
    fallbacks = sum(1 for s in steps if s.get("fallback"))
    retries = sum(1 for s in steps if s.get("retry"))
    guards = sum(1 for s in steps if s.get("submit_guard"))
    lats = [s["llm_latency"] for s in steps
            if isinstance(s.get("llm_latency"), (int, float))]
    avg_lat = sum(lats) / max(len(lats), 1) if lats else 0
    adhs = [s["adherence"] for s in steps if isinstance(s.get("adherence"), (int, float))]
    avg_adh = sum(adhs) / max(len(adhs), 1) if adhs else 0
    urls = [s.get("url", "") for s in steps]
    loop = False
    if len(urls) >= 12:
        for i in range(len(urls) - 11):
            if len(set(urls[i:i+12])) == 1: loop = True; break
    last3 = [{"step": s.get("step"), "action": s.get("action_desc", "?")[:60],
              "plan": (s.get("plan", "") or "")[:80]} for s in steps[-3:]]
    return {"types": types, "clicks": clicks, "fallbacks": fallbacks,
            "retries": retries, "guards": guards, "avg_lat": round(avg_lat, 2),
            "avg_adh": round(avg_adh, 2), "loop": loop, "last3": last3}


def main():
    REPORTS_DIR.mkdir(exist_ok=True)

    print()
    print("═" * 60)
    print("  v1.2 VALIDATION RUNNER")
    print("═" * 60)

    # Run agent
    print(f"\n  ▶ Running {AGENT.name} ...")
    t0 = time.time()
    result = subprocess.run(
        [str(PYTHON), str(AGENT), "--scenarios", str(SCENARIOS)],
        cwd=str(SCRIPT_DIR), capture_output=False, text=True)
    elapsed = time.time() - t0
    print(f"\n  Finished in {elapsed:.1f}s  (exit={result.returncode})")

    # Load results
    rd = newest_run()
    if not rd:
        print("  ❌ No run dir found"); sys.exit(1)

    summ = json.loads((rd / "summary.json").read_text())
    traces = {}
    for tf in rd.glob("trace_*.json"):
        d = json.loads(tf.read_text())
        traces[d.get("scenario", {}).get("name", tf.stem)] = d

    # Analyze
    v12 = []
    for sc in summ:
        name = sc["name"]
        td = traces.get(name, {"steps": []})
        m = analyze_trace(td)
        v12.append({"name": name, "success": sc["success"],
                     "steps": sc["steps_taken"], "reason": sc.get("reason", ""),
                     "adherence": sc.get("avg_adherence", m["avg_adh"]),
                     **m})

    # ─── Generate reports ───

    # 01_summary.md
    ok12 = sum(1 for r in v12 if r["success"])
    ok11 = sum(1 for r in V11_BASELINE if r["success"])
    summary_md = f"""# v1.2 Validation Summary

| Metric | v1.1 | v1.2 | Change |
|--------|------|------|--------|
| Success Rate | {ok11}/4 ({ok11*25}%) | {ok12}/4 ({ok12*25}%) | {"↑" if ok12 > ok11 else "→" if ok12 == ok11 else "↓"} |
| Avg Steps (success) | {sum(r['steps_taken'] for r in V11_BASELINE if r['success'])/max(ok11,1):.1f} | {sum(r['steps'] for r in v12 if r['success'])/max(ok12,1):.1f} | |
| Avg Adherence | N/A | {sum(r['adherence'] for r in v12)/4:.2f} | NEW |

## Per-Scenario Results

| # | Scenario | v1.1 | v1.2 | Steps | Adherence | Reason |
|---|----------|------|------|-------|-----------|--------|
"""
    for i, (r12, r11) in enumerate(zip(v12, V11_BASELINE), 1):
        s11 = "✅" if r11["success"] else "❌"
        s12 = "✅" if r12["success"] else "❌"
        summary_md += (f"| {i} | {r12['name'][:35]} | {s11} | {s12} | "
                       f"{r12['steps']} | {r12['adherence']:.2f} | "
                       f"{r12['reason'][:40]} |\n")

    summary_md += f"\n**Run directory**: `{rd}`\n"
    (REPORTS_DIR / "01_summary.md").write_text(summary_md)

    # 02_failures_and_fixes.md
    failures_md = "# Failure Analysis & Fixes\n\n"
    for r in v12:
        if not r["success"]:
            failures_md += f"## ❌ {r['name']}\n\n"
            failures_md += f"- **Reason**: {r['reason']}\n"
            failures_md += f"- **Steps**: {r['steps']} | TYPE: {r['types']} | CLICK: {r['clicks']}\n"
            failures_md += f"- **Retries**: {r['retries']} | Guards: {r['guards']} | Fallbacks: {r['fallbacks']}\n"
            failures_md += f"- **Loop**: {'Yes' if r['loop'] else 'No'}\n"
            failures_md += f"- **Adherence**: {r['adherence']:.2f}\n\n"
            failures_md += "### Last 3 Actions\n\n"
            for a in r["last3"]:
                failures_md += f"- Step {a['step']}: `{a['action']}`\n"
                if a["plan"]:
                    failures_md += f"  Plan: {a['plan']}\n"
            failures_md += "\n"

    succeeded = [r for r in v12 if r["success"]]
    if succeeded:
        failures_md += "## ✅ Successes\n\n"
        for r in succeeded:
            failures_md += f"- **{r['name']}**: {r['steps']} steps, adherence={r['adherence']:.2f}\n"

    (REPORTS_DIR / "02_failures_and_fixes.md").write_text(failures_md)

    # 03_metrics_table.md
    metrics_md = "# Detailed Metrics Table\n\n"
    metrics_md += "| Scenario | OK | Steps | TYPE | CLICK | FB | Retry | Guard | Loop | Latency | Adherence |\n"
    metrics_md += "|----------|-----|-------|------|-------|-----|-------|-------|------|---------|-----------|\n"
    for r in v12:
        s = "✅" if r["success"] else "❌"
        metrics_md += (f"| {r['name'][:30]} | {s} | {r['steps']} | {r['types']} | "
                       f"{r['clicks']} | {r['fallbacks']} | {r['retries']} | "
                       f"{r['guards']} | {'Y' if r['loop'] else 'N'} | "
                       f"{r['avg_lat']:.2f}s | {r['adherence']:.2f} |\n")
    metrics_md += f"\n## v1.1 Comparison\n\n"
    metrics_md += "| Scenario | v1.1 OK | v1.2 OK | v1.1 Steps | v1.2 Steps | Δ |\n"
    metrics_md += "|----------|---------|---------|------------|------------|---|\n"
    for r12, r11 in zip(v12, V11_BASELINE):
        s11 = "✅" if r11["success"] else "❌"
        s12 = "✅" if r12["success"] else "❌"
        delta = r12["steps"] - r11["steps_taken"]
        metrics_md += (f"| {r12['name'][:30]} | {s11} | {s12} | "
                       f"{r11['steps_taken']} | {r12['steps']} | "
                       f"{'+' if delta > 0 else ''}{delta} |\n")
    (REPORTS_DIR / "03_metrics_table.md").write_text(metrics_md)

    # Console output
    print()
    print("═" * 60)
    print("  v1.2 VALIDATION REPORT")
    print("═" * 60)
    print(f"  {'#':>2}  {'OK':>3}  {'Stp':>4}  {'TY':>3}  {'CK':>3}  "
          f"{'Adh':>5}  {'Lp':>3}  Name")
    print(f"  {'─' * 55}")
    for i, r in enumerate(v12, 1):
        s = "✅" if r["success"] else "❌"
        lp = "Y" if r["loop"] else "N"
        print(f"  {i:>2}  {s:>3}  {r['steps']:>4}  {r['types']:>3}  "
              f"{r['clicks']:>3}  {r['adherence']:>5.2f}  {lp:>3}  "
              f"{r['name'][:30]}")

    print(f"\n  Success: {ok12}/4 ({ok12*25}%)  │  "
          f"v1.1 was: {ok11}/4 ({ok11*25}%)")
    print(f"\n  📁 Reports: {REPORTS_DIR}")
    print(f"  📁 Run:     {rd}")
    print()
    print("═" * 60)
    print("  VALIDATION COMPLETE")
    print("═" * 60)


if __name__ == "__main__":
    main()
