#!/usr/bin/env python3
"""
Cross-Domain Evaluation Harness for VLA Agent v1.3.

Runs 10 scenarios across 5 domains (Wikipedia, Google, YouTube, Store, Booking),
collects metrics, generates CSV/JSON results and markdown reports.

Usage:
    python cross_domain_eval_v1_3.py
"""

import csv
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

SCRIPT_DIR   = Path(__file__).resolve().parent
AGENT        = SCRIPT_DIR / "vla_unified_agent_v1_3.py"
SCENARIOS    = SCRIPT_DIR / "cross_domain_scenarios_v1_3.json"
RUNS_DIR     = SCRIPT_DIR / "runs"
REPORTS_DIR  = SCRIPT_DIR / "reports_cross_domain_v1_3"
PYTHON       = SCRIPT_DIR / ".venv" / "bin" / "python"
if not PYTHON.exists():
    PYTHON = Path(sys.executable)


# ═══════════════════════════════════════════════════════════════
#  Helpers
# ═══════════════════════════════════════════════════════════════
def newest_run():
    if not RUNS_DIR.exists():
        return None
    dirs = sorted([d for d in RUNS_DIR.iterdir() if d.is_dir()],
                  key=lambda d: d.stat().st_mtime, reverse=True)
    return dirs[0] if dirs else None


def detect_domain(url):
    u = url.lower()
    if "localhost:8001" in u: return "store"
    if "localhost:8002" in u: return "booking"
    if "wikipedia" in u:     return "wikipedia"
    if "youtube" in u:       return "youtube"
    if "google" in u:        return "google"
    return "other"


def analyze_trace(data):
    """Extract metrics from a trace file."""
    steps = data.get("steps", [])
    scenario = data.get("scenario", {})
    groundings = data.get("groundings", [])

    types  = sum(1 for s in steps if s.get("action_type") == "TYPE")
    clicks = sum(1 for s in steps if s.get("action_type") == "CLICK")
    fbs    = sum(1 for s in steps if s.get("fallback"))
    retries = sum(1 for s in steps if s.get("retry"))
    guards  = sum(1 for s in steps if s.get("submit_guard"))
    gnd     = sum(1 for g in groundings if g.get("was_grounded"))

    lats = [s["llm_latency"] for s in steps
            if isinstance(s.get("llm_latency"), (int, float))]
    avg_lat = round(sum(lats) / max(len(lats), 1), 2) if lats else 0

    adhs = [s["adherence"] for s in steps
            if isinstance(s.get("adherence"), (int, float))]
    avg_adh = round(sum(adhs) / max(len(adhs), 1), 2) if adhs else 0

    urls = [s.get("url", "") for s in steps]
    loop = False
    if len(urls) >= 12:
        for i in range(len(urls) - 11):
            if len(set(urls[i:i+12])) == 1:
                loop = True
                break

    last3 = [{"step": s.get("step"), "action": s.get("action_desc", "?")[:55],
              "plan": (s.get("plan", "") or "")[:60]}
             for s in steps[-3:]]

    return {
        "types": types, "clicks": clicks, "fallbacks": fbs,
        "retries": retries, "guards": guards, "groundings": gnd,
        "avg_lat": avg_lat, "avg_adh": avg_adh, "loop": loop,
        "last3": last3,
    }


# ═══════════════════════════════════════════════════════════════
#  Main
# ═══════════════════════════════════════════════════════════════
def main():
    REPORTS_DIR.mkdir(exist_ok=True)

    print()
    print("═" * 64)
    print("  CROSS-DOMAIN EVALUATION — VLA v1.3")
    print("═" * 64)
    print(f"  Agent:     {AGENT.name}")
    print(f"  Scenarios: {SCENARIOS.name}  (10 tasks × 5 domains)")
    print(f"  Reports:   {REPORTS_DIR}")
    print("═" * 64)

    # ── Run agent ──
    print(f"\n  ▶ Running agent across all domains ...")
    t0 = time.time()
    proc = subprocess.run(
        [str(PYTHON), str(AGENT), "--scenarios", str(SCENARIOS)],
        cwd=str(SCRIPT_DIR), capture_output=False, text=True)
    elapsed = time.time() - t0
    print(f"\n  Finished in {elapsed:.1f}s  (exit={proc.returncode})")

    # ── Load results ──
    rd = newest_run()
    if not rd:
        print("  ❌ No run directory found")
        sys.exit(1)

    summary_file = rd / "summary.json"
    if not summary_file.exists():
        print(f"  ❌ summary.json not found in {rd}")
        sys.exit(1)

    summ = json.loads(summary_file.read_text())

    traces = {}
    for tf in rd.glob("trace_*.json"):
        d = json.loads(tf.read_text())
        name = d.get("scenario", {}).get("name", tf.stem)
        traces[name] = d

    # ── Analyze ──
    results = []
    for sc in summ:
        name = sc["name"]
        domain = detect_domain(sc.get("start_url", ""))
        td = traces.get(name, {"steps": [], "groundings": []})
        m = analyze_trace(td)
        results.append({
            "name": name,
            "domain": domain,
            "success": sc.get("success", False),
            "steps": sc.get("steps_taken", 0),
            "reason": sc.get("reason", ""),
            "final_url": sc.get("final_url", ""),
            "adherence": sc.get("avg_adherence", m["avg_adh"]),
            **m,
        })

    # ── Save CSV ──
    csv_path = SCRIPT_DIR / "results_cross_domain_v1_3.csv"
    with open(csv_path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["name", "domain", "success", "steps", "types", "clicks",
                     "fallbacks", "retries", "guards", "groundings",
                     "avg_latency", "adherence", "loop", "reason"])
        for r in results:
            w.writerow([r["name"], r["domain"], r["success"], r["steps"],
                        r["types"], r["clicks"], r["fallbacks"], r["retries"],
                        r["guards"], r["groundings"], r["avg_lat"],
                        r["adherence"], r["loop"], r["reason"]])
    print(f"\n  📊 CSV: {csv_path}")

    # ── Save JSON ──
    json_path = SCRIPT_DIR / "results_cross_domain_v1_3.json"
    with open(json_path, "w") as f:
        json.dump({"timestamp": datetime.now().isoformat(),
                   "run_dir": str(rd),
                   "total_time_seconds": round(elapsed, 1),
                   "results": results}, f, indent=2)
    print(f"  📊 JSON: {json_path}")

    # ── Domain stats ──
    domains = {}
    for r in results:
        d = r["domain"]
        if d not in domains:
            domains[d] = {"total": 0, "ok": 0, "steps": [], "lats": [],
                          "adhs": [], "gnds": 0, "loops": 0}
        domains[d]["total"] += 1
        if r["success"]:
            domains[d]["ok"] += 1
        domains[d]["steps"].append(r["steps"])
        domains[d]["lats"].append(r["avg_lat"])
        domains[d]["adhs"].append(r["adherence"])
        domains[d]["gnds"] += r["groundings"]
        if r["loop"]:
            domains[d]["loops"] += 1

    total = len(results)
    ok_total = sum(1 for r in results if r["success"])

    # ═══════════════════════════════════════════════════════════
    #  Generate Reports
    # ═══════════════════════════════════════════════════════════

    # ── 01_summary.md ──
    sm = "# Cross-Domain Evaluation Summary — v1.3\n\n"
    sm += f"**Date**: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
    sm += f"**Run dir**: `{rd}`\n"
    sm += f"**Total time**: {elapsed:.0f}s\n\n"
    sm += "## Overall\n\n"
    sm += f"| Metric | Value |\n|--------|-------|\n"
    sm += f"| Success Rate | {ok_total}/{total} ({ok_total/max(total,1)*100:.0f}%) |\n"
    avg_steps_ok = (sum(r["steps"] for r in results if r["success"])
                    / max(ok_total, 1))
    avg_lat_all = sum(r["avg_lat"] for r in results) / max(total, 1)
    avg_adh_all = sum(r["adherence"] for r in results) / max(total, 1)
    sm += f"| Avg Steps (success) | {avg_steps_ok:.1f} |\n"
    sm += f"| Avg Latency | {avg_lat_all:.2f}s |\n"
    sm += f"| Avg Adherence | {avg_adh_all:.2f} |\n"
    sm += f"| Total Groundings | {sum(r['groundings'] for r in results)} |\n\n"

    sm += "## Per-Scenario Results\n\n"
    sm += "| # | Domain | Scenario | OK | Steps | Adh | Reason |\n"
    sm += "|---|--------|----------|----|-------|-----|--------|\n"
    for i, r in enumerate(results, 1):
        s = "✅" if r["success"] else "❌"
        sm += (f"| {i} | {r['domain']:<10} | {r['name'][:32]} | {s} | "
               f"{r['steps']} | {r['adherence']:.2f} | "
               f"{r['reason'][:35]} |\n")
    (REPORTS_DIR / "01_summary.md").write_text(sm)

    # ── 02_domain_breakdown.md ──
    db = "# Domain Breakdown — v1.3 Cross-Domain\n\n"
    db += ("| Domain | Success | Rate | Avg Steps | Avg Latency | "
           "Avg Adherence | Groundings | Loops |\n")
    db += ("|--------|---------|------|-----------|-------------|"
           "--------------|------------|-------|\n")
    for d in ["wikipedia", "google", "youtube", "store", "booking"]:
        if d not in domains:
            continue
        ds = domains[d]
        rate = f"{ds['ok']}/{ds['total']}"
        pct = ds["ok"] / max(ds["total"], 1) * 100
        avg_s = sum(ds["steps"]) / max(len(ds["steps"]), 1)
        avg_l = sum(ds["lats"]) / max(len(ds["lats"]), 1)
        avg_a = sum(ds["adhs"]) / max(len(ds["adhs"]), 1)
        db += (f"| {d:<10} | {rate} | {pct:.0f}% | {avg_s:.1f} | "
               f"{avg_l:.2f}s | {avg_a:.2f} | {ds['gnds']} | "
               f"{ds['loops']} |\n")
    db += f"\n**Overall**: {ok_total}/{total} ({ok_total/max(total,1)*100:.0f}%)\n"

    # Per-domain detail
    for d in ["wikipedia", "google", "youtube", "store", "booking"]:
        dr = [r for r in results if r["domain"] == d]
        if not dr:
            continue
        db += f"\n## {d.capitalize()}\n\n"
        for r in dr:
            s = "✅" if r["success"] else "❌"
            db += f"- {s} **{r['name']}** — {r['steps']} steps"
            if not r["success"]:
                db += f" — _{r['reason'][:50]}_"
                db += f"\n  Last actions: "
                for a in r.get("last3", []):
                    db += f"`{a['action'][:40]}` → "
            db += "\n"
    (REPORTS_DIR / "02_domain_breakdown.md").write_text(db)

    # ── 03_generalization_analysis.md ──
    ga = "# Generalization Analysis — v1.3\n\n"
    ga += "## Can v1.3 generalize across domains?\n\n"

    local_ok = sum(1 for r in results
                   if r["domain"] in ("store", "booking") and r["success"])
    local_tot = sum(1 for r in results
                    if r["domain"] in ("store", "booking"))
    public_ok = sum(1 for r in results
                    if r["domain"] in ("wikipedia", "google", "youtube")
                    and r["success"])
    public_tot = sum(1 for r in results
                     if r["domain"] in ("wikipedia", "google", "youtube"))

    ga += "| Category | Success | Rate |\n"
    ga += "|----------|---------|------|\n"
    ga += (f"| Local apps (Store + Booking) | {local_ok}/{local_tot} | "
           f"{local_ok/max(local_tot,1)*100:.0f}% |\n")
    ga += (f"| Public web (Wiki + Google + YT) | {public_ok}/{public_tot} | "
           f"{public_ok/max(public_tot,1)*100:.0f}% |\n")
    ga += (f"| **Overall** | **{ok_total}/{total}** | "
           f"**{ok_total/max(total,1)*100:.0f}%** |\n\n")

    # Failure analysis
    failures = [r for r in results if not r["success"]]
    if failures:
        ga += "## Failure Analysis\n\n"
        for r in failures:
            ga += f"### ❌ {r['name']} ({r['domain']})\n\n"
            ga += f"- **Reason**: {r['reason']}\n"
            ga += f"- **Steps**: {r['steps']} | TYPE: {r['types']} | CLICK: {r['clicks']}\n"
            ga += f"- **Final URL**: {r['final_url'][:70]}\n"
            ga += f"- **Adherence**: {r['adherence']:.2f}\n"
            if r.get("last3"):
                ga += "- **Last 3 actions**:\n"
                for a in r["last3"]:
                    ga += f"  - Step {a['step']}: `{a['action'][:50]}`\n"
            ga += "\n"
    else:
        ga += "## 🎉 No Failures!\n\nAll 10 scenarios across 5 domains succeeded.\n\n"

    # Strengths
    ga += "## Strengths\n\n"
    strong = [d for d, ds in domains.items() if ds["ok"] == ds["total"]]
    if strong:
        ga += f"- Perfect score on: **{', '.join(strong)}**\n"
    ga += f"- Total actions: {sum(r['types']+r['clicks'] for r in results)}\n"
    ga += f"- No loops triggered: {sum(1 for r in results if r['loop'])} scenarios\n"

    # Weaknesses
    weak = [d for d, ds in domains.items() if ds["ok"] < ds["total"]]
    if weak:
        ga += "\n## Weaknesses\n\n"
        for d in weak:
            ds = domains[d]
            ga += f"- **{d}**: {ds['ok']}/{ds['total']} success\n"

    (REPORTS_DIR / "03_generalization_analysis.md").write_text(ga)

    # ═══════════════════════════════════════════════════════════
    #  Console Output
    # ═══════════════════════════════════════════════════════════
    print()
    print("═" * 64)
    print("  CROSS-DOMAIN RESULTS — v1.3")
    print("═" * 64)
    print()
    print(f"  {'Domain':<12} {'Success':<10} {'Rate':<8} {'Avg Stp':<9} "
          f"{'Avg Lat':<9} {'Adh':<6}")
    print(f"  {'─' * 55}")
    for d in ["wikipedia", "google", "youtube", "store", "booking"]:
        if d not in domains:
            continue
        ds = domains[d]
        rate_s = f"{ds['ok']}/{ds['total']}"
        pct = f"{ds['ok']/max(ds['total'],1)*100:.0f}%"
        avg_s = sum(ds["steps"]) / max(len(ds["steps"]), 1)
        avg_l = sum(ds["lats"]) / max(len(ds["lats"]), 1)
        avg_a = sum(ds["adhs"]) / max(len(ds["adhs"]), 1)
        print(f"  {d:<12} {rate_s:<10} {pct:<8} {avg_s:<9.1f} "
              f"{avg_l:<9.2f} {avg_a:<6.2f}")
    print(f"  {'─' * 55}")
    avg_steps = sum(r["steps"] for r in results) / max(total, 1)
    print(f"  {'TOTAL':<12} {ok_total}/{total:<8} "
          f"{ok_total/max(total,1)*100:.0f}%{'':5} "
          f"{avg_steps:<9.1f} {avg_lat_all:<9.2f} {avg_adh_all:<6.2f}")
    print()

    print(f"  Per-scenario details:")
    print(f"  {'#':>3} {'OK':>3} {'Stp':>4} {'Dom':<10} {'Name':<32} Reason")
    print(f"  {'─' * 75}")
    for i, r in enumerate(results, 1):
        s = "✅" if r["success"] else "❌"
        print(f"  {i:>3} {s:>3} {r['steps']:>4} {r['domain']:<10} "
              f"{r['name'][:32]:<32} {r['reason'][:28]}")

    print(f"\n  📊 CSV:     {csv_path}")
    print(f"  📊 JSON:    {json_path}")
    print(f"  📁 Reports: {REPORTS_DIR}")
    print(f"  📁 Run:     {rd}")
    print()
    print("═" * 64)
    print("  CROSS-DOMAIN EVALUATION COMPLETE.")
    print("  READY FOR MULTI-DOMAIN COMPOSITE TASKS.")
    print("═" * 64)


if __name__ == "__main__":
    main()
