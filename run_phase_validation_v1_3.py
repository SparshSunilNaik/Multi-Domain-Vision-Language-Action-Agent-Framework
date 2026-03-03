#!/usr/bin/env python3
"""
Validation Runner for v1.3 — Input Grounding evaluation.
Runs Store/Booking scenarios and generates comparison reports.
"""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
AGENT = SCRIPT_DIR / "vla_unified_agent_v1_3.py"
SCENARIOS = SCRIPT_DIR / "test_scenarios_phase_store_booking.json"
RUNS_DIR = SCRIPT_DIR / "runs"
REPORTS_DIR = SCRIPT_DIR / "reports_unified_v1_3"
PYTHON = SCRIPT_DIR / ".venv" / "bin" / "python"
if not PYTHON.exists():
    PYTHON = Path(sys.executable)

V12_BASELINE = [
    {"name": "Store — Single Item Purchase", "success": True, "steps": 7,
     "types": 3, "clicks": 4, "latency": 4.05, "adherence": 0.26, "loop": False,
     "groundings": 0},
    {"name": "Store — Multi Item Purchase", "success": True, "steps": 9,
     "types": 4, "clicks": 5, "latency": 3.20, "adherence": 0.31, "loop": False,
     "groundings": 0},
    {"name": "Booking — Hotel Reservation", "success": True, "steps": 7,
     "types": 3, "clicks": 4, "latency": 3.29, "adherence": 0.27, "loop": False,
     "groundings": 0},
    {"name": "Booking — Doctor Appointment", "success": False, "steps": 30,
     "types": 20, "clicks": 10, "latency": 5.10, "adherence": 0.12, "loop": False,
     "groundings": 0},
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
    lats = [s["llm_latency"] for s in steps if isinstance(s.get("llm_latency"), (int, float))]
    avg_lat = sum(lats) / max(len(lats), 1) if lats else 0
    adhs = [s["adherence"] for s in steps if isinstance(s.get("adherence"), (int, float))]
    avg_adh = sum(adhs) / max(len(adhs), 1) if adhs else 0

    # Grounding analysis
    groundings = data.get("groundings", [])
    gnd_applied = sum(1 for g in groundings if g.get("was_grounded"))
    gnd_details = [g for g in groundings if g.get("was_grounded")]

    urls = [s.get("url", "") for s in steps]
    loop = False
    if len(urls) >= 12:
        for i in range(len(urls) - 11):
            if len(set(urls[i:i+12])) == 1: loop = True; break

    last3 = [{"step": s.get("step"), "action": s.get("action_desc", "?")[:60],
              "plan": (s.get("plan", "") or "")[:80]} for s in steps[-3:]]

    return {"types": types, "clicks": clicks, "fallbacks": fallbacks,
            "retries": retries, "guards": guards, "avg_lat": round(avg_lat, 2),
            "avg_adh": round(avg_adh, 2), "loop": loop, "last3": last3,
            "gnd_applied": gnd_applied, "gnd_details": gnd_details}


def main():
    REPORTS_DIR.mkdir(exist_ok=True)

    print()
    print("═" * 60)
    print("  v1.3 VALIDATION RUNNER — INPUT GROUNDING")
    print("═" * 60)

    print(f"\n  ▶ Running {AGENT.name} ...")
    t0 = time.time()
    result = subprocess.run(
        [str(PYTHON), str(AGENT), "--scenarios", str(SCENARIOS)],
        cwd=str(SCRIPT_DIR), capture_output=False, text=True)
    elapsed = time.time() - t0
    print(f"\n  Finished in {elapsed:.1f}s  (exit={result.returncode})")

    rd = newest_run()
    if not rd:
        print("  ❌ No run dir found"); sys.exit(1)

    summ = json.loads((rd / "summary.json").read_text())
    traces = {}
    for tf in rd.glob("trace_*.json"):
        d = json.loads(tf.read_text())
        traces[d.get("scenario", {}).get("name", tf.stem)] = d

    v13 = []
    for sc in summ:
        name = sc["name"]
        td = traces.get(name, {"steps": [], "groundings": []})
        m = analyze_trace(td)
        v13.append({"name": name, "success": sc["success"],
                     "steps": sc["steps_taken"], "reason": sc.get("reason", ""),
                     "adherence": sc.get("avg_adherence", m["avg_adh"]),
                     **m})

    ok13 = sum(1 for r in v13 if r["success"])
    ok12 = sum(1 for r in V12_BASELINE if r["success"])

    # ─── 01_summary.md ───
    summary_md = f"""# v1.3 Validation Summary — Input Grounding

| Metric | v1.2 | v1.3 | Change |
|--------|------|------|--------|
| Success Rate | {ok12}/4 ({ok12*25}%) | {ok13}/4 ({ok13*25}%) | {"↑" if ok13 > ok12 else "→" if ok13 == ok12 else "↓"} |
| Total Groundings | 0 | {sum(r['gnd_applied'] for r in v13)} | NEW |
| Avg Adherence | {sum(r['adherence'] for r in V12_BASELINE)/4:.2f} | {sum(r['adherence'] for r in v13)/4:.2f} | |

## Per-Scenario Results

| # | Scenario | v1.2 | v1.3 | Steps | Adh | Gnd | Reason |
|---|----------|------|------|-------|-----|-----|--------|
"""
    for i, (r13, r12) in enumerate(zip(v13, V12_BASELINE), 1):
        s12 = "✅" if r12["success"] else "❌"
        s13 = "✅" if r13["success"] else "❌"
        summary_md += (f"| {i} | {r13['name'][:35]} | {s12} | {s13} | "
                       f"{r13['steps']} | {r13['adherence']:.2f} | "
                       f"{r13['gnd_applied']} | {r13['reason'][:35]} |\n")

    summary_md += f"\n**Run directory**: `{rd}`\n"
    (REPORTS_DIR / "01_summary.md").write_text(summary_md)

    # ─── 02_grounding_analysis.md ───
    gnd_md = "# Input Grounding Analysis\n\n"
    gnd_md += "## Grounding Events\n\n"
    gnd_md += "| Scenario | Field | Type | Original | Normalized | Impact |\n"
    gnd_md += "|----------|-------|------|----------|------------|--------|\n"
    for r in v13:
        for g in r.get("gnd_details", []):
            impact = "✅ Fixed" if r["success"] else "⚠ Helped"
            gnd_md += (f"| {r['name'][:25]} | {g.get('field_name', '?')[:15]} | "
                       f"{g.get('field_type', '?')} | {g.get('original_text', '?')[:20]} | "
                       f"{g.get('normalized_text', '?')[:20]} | {impact} |\n")

    gnd_md += "\n## Summary\n\n"
    total_gnd = sum(r['gnd_applied'] for r in v13)
    gnd_md += f"- **Total grounding events**: {total_gnd}\n"
    gnd_md += f"- **Scenarios benefiting**: {sum(1 for r in v13 if r['gnd_applied'] > 0)}/4\n"

    # Doctor appointment specific
    doc = next((r for r in v13 if "doctor" in r["name"].lower()), None)
    if doc:
        gnd_md += f"\n### Doctor Appointment (key target)\n\n"
        gnd_md += f"- Success: {'✅' if doc['success'] else '❌'}\n"
        gnd_md += f"- Steps: {doc['steps']}\n"
        gnd_md += f"- Groundings applied: {doc['gnd_applied']}\n"
        if doc.get("gnd_details"):
            gnd_md += f"- Date conversion: {doc['gnd_details'][0].get('original_text', '?')} → {doc['gnd_details'][0].get('normalized_text', '?')}\n"

    (REPORTS_DIR / "02_grounding_analysis.md").write_text(gnd_md)

    # ─── 03_metrics_table.md ───
    met_md = "# Detailed Metrics — v1.3\n\n"
    met_md += "| Scenario | OK | Steps | TYPE | CLICK | FB | RT | Grd | Loop | Lat | Adh |\n"
    met_md += "|----------|-----|-------|------|-------|-----|-----|-----|------|-----|-----|\n"
    for r in v13:
        s = "✅" if r["success"] else "❌"
        met_md += (f"| {r['name'][:28]} | {s} | {r['steps']} | {r['types']} | "
                   f"{r['clicks']} | {r['fallbacks']} | {r['retries']} | "
                   f"{r['gnd_applied']} | {'Y' if r['loop'] else 'N'} | "
                   f"{r['avg_lat']:.1f}s | {r['adherence']:.2f} |\n")
    met_md += f"\n## Cross-Version Comparison\n\n"
    met_md += "| Scenario | v1.0 | v1.1 | v1.2 | v1.3 | Steps (v1.3) |\n"
    met_md += "|----------|------|------|------|------|-------------|\n"
    v10 = ["❌"] * 4
    v11 = ["✅", "❌", "❌", "❌"]
    for i, r in enumerate(v13):
        s12 = "✅" if V12_BASELINE[i]["success"] else "❌"
        s13 = "✅" if r["success"] else "❌"
        met_md += f"| {r['name'][:28]} | {v10[i]} | {v11[i]} | {s12} | {s13} | {r['steps']} |\n"
    (REPORTS_DIR / "03_metrics_table.md").write_text(met_md)

    # Console output
    print()
    print("═" * 60)
    print("  v1.3 VALIDATION REPORT")
    print("═" * 60)
    print(f"  {'#':>2}  {'OK':>3}  {'Stp':>4}  {'TY':>3}  {'CK':>3}  "
          f"{'Gnd':>3}  {'Adh':>5}  Name")
    print(f"  {'─' * 55}")
    for i, r in enumerate(v13, 1):
        s = "✅" if r["success"] else "❌"
        print(f"  {i:>2}  {s:>3}  {r['steps']:>4}  {r['types']:>3}  "
              f"{r['clicks']:>3}  {r['gnd_applied']:>3}  {r['adherence']:>5.2f}  "
              f"{r['name'][:30]}")

    print(f"\n  Success: {ok13}/4 ({ok13*25}%)  │  v1.2 was: {ok12}/4 ({ok12*25}%)")
    print(f"  Total groundings applied: {sum(r['gnd_applied'] for r in v13)}")
    print(f"\n  📁 Reports: {REPORTS_DIR}")
    print(f"  📁 Run:     {rd}")
    print()
    print("═" * 60)
    print("  VALIDATION COMPLETE")
    print("═" * 60)


if __name__ == "__main__":
    main()
