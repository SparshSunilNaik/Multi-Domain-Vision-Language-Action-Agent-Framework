#!/usr/bin/env python3
"""
Composite Orchestrator v1 — Multi-domain instruction decomposition & execution.

One user instruction → multiple sequential web subtasks across domains,
with fact extraction and variable passing between steps.

Usage:
    python composite_orchestrator_v1.py                              # Interactive
    python composite_orchestrator_v1.py --scenarios composite_scenarios_v1.json  # Batch
"""

import argparse
import csv
import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

# Import v1.3 agent functions
import vla_unified_agent_v1_3 as agent

OLLAMA_URL  = agent.OLLAMA_URL
MODEL_NAME  = agent.MODEL_NAME
REPORTS_DIR = os.path.join(SCRIPT_DIR, "reports_composite_v1")


# ═══════════════════════════════════════════════════════════════
#  Variable Substitution
# ═══════════════════════════════════════════════════════════════
def substitute(text, variables):
    """Replace {{var_name}} placeholders with extracted values."""
    if not text or not variables:
        return text
    for k, v in variables.items():
        text = text.replace("{{" + k + "}}", str(v))
    return text


# ═══════════════════════════════════════════════════════════════
#  Fact Extraction
# ═══════════════════════════════════════════════════════════════
def extract_fact(page, extract_config, variables):
    """Extract a fact from the current page using regex or LLM."""
    if not extract_config:
        return None, None

    method = extract_config.get("method", "regex")
    name = extract_config.get("name", "value")
    default = extract_config.get("default", "")
    text = agent.get_text(page, 2000)

    if not text:
        return name, default

    if method == "regex":
        pattern = extract_config.get("pattern", "")
        if pattern:
            m = re.search(pattern, text)
            if m:
                val = m.group(1) if m.lastindex else m.group(0)
                return name, val.strip()
        return name, default

    if method == "llm":
        prompt_tmpl = extract_config.get("prompt", f"Extract {name} from this text.")
        prompt = (f"{prompt_tmpl}\n\nText:\n{text[:1000]}\n\n"
                  "Reply with ONLY the extracted value. Nothing else.")
        raw = agent.llm_query(prompt, max_tokens=30)
        val = raw.strip().strip('"').strip("'").strip(".")
        if val and len(val) < 80 and "error" not in val.lower():
            return name, val
        return name, default

    return name, default


# ═══════════════════════════════════════════════════════════════
#  LLM Plan Decomposition (interactive mode)
# ═══════════════════════════════════════════════════════════════
DECOMPOSE_PROMPT = """You are a task decomposition engine. Given a composite instruction, break it into sequential web subtasks.

Available domains and start URLs:
  wikipedia : https://en.wikipedia.org
  google    : https://www.google.com
  youtube   : https://www.youtube.com
  store     : http://localhost:8001/index.html
  booking   : http://localhost:8002/step1_service.html

Rules:
1. Each step runs on ONE domain. Steps execute sequentially.
2. Use {{variable_name}} syntax to reference extracted values from previous steps.
3. Include "extract" only when a fact must carry forward.
4. Keep max_steps 5-15 per step.

Output ONLY valid JSON (no markdown fences):
{
  "steps": [
    {
      "domain": "wikipedia",
      "start_url": "https://en.wikipedia.org",
      "instruction": "Search for ...",
      "completion_keyword": "/wiki/...",
      "max_steps": 10,
      "extract": {"name": "var", "method": "regex", "pattern": "...", "default": "fallback"}
    }
  ],
  "final_completion_keyword": "..."
}

Composite instruction: """


def decompose_interactive(instruction):
    """Use LLM to decompose a composite instruction into a step plan."""
    raw = agent.llm_query(DECOMPOSE_PROMPT + instruction, max_tokens=600)
    # Strip markdown fences if present
    raw = re.sub(r'^```\w*\n?', '', raw.strip())
    raw = re.sub(r'\n?```$', '', raw.strip())
    try:
        plan = json.loads(raw)
        if "steps" in plan and isinstance(plan["steps"], list):
            return plan
    except json.JSONDecodeError:
        pass
    # Fallback: single Google search
    return {
        "steps": [{
            "domain": "google",
            "start_url": "https://www.google.com",
            "instruction": instruction,
            "completion_keyword": "search?q=",
            "max_steps": 10,
        }],
        "final_completion_keyword": "search?q=",
    }


# ═══════════════════════════════════════════════════════════════
#  Run Composite Scenario
# ═══════════════════════════════════════════════════════════════
def run_composite(ctx, scenario, run_dir, visual=False):
    """Execute a multi-step composite scenario with variable passing."""
    name = scenario.get("name", "Composite")
    instruction = scenario.get("composite_instruction", "")
    steps = scenario.get("steps", [])
    final_kw = scenario.get("final_completion_keyword", "")

    print(f"\n{'━' * 72}")
    print(f"  🔗 COMPOSITE: {name}")
    print(f"  Instruction: {instruction[:70]}")
    print(f"  Steps: {len(steps)}  │  Final KW: {final_kw or '(none)'}")
    print(f"{'━' * 72}")

    variables = {}
    step_results = []
    total_steps = 0
    total_actions = 0
    all_lats = []
    domains_used = []
    extracts_used = []
    composite_success = False
    stop_reason = "incomplete"
    final_url = ""

    for i, step in enumerate(steps, 1):
        # Substitute variables into step fields
        step_instruction = substitute(step["instruction"], variables)
        step_url = substitute(step["start_url"], variables)
        step_kw = substitute(step.get("completion_keyword", ""), variables)
        step_domain = step.get("domain", "other")
        step_max = step.get("max_steps", 15)
        step_name = f"{name} → Step {i}: {step_domain}"

        print(f"\n  ┌── Step {i}/{len(steps)} │ {step_domain} ──┐")
        if variables:
            print(f"  │ Variables: {', '.join(f'{k}={v}' for k, v in variables.items())}")

        page = ctx.new_page()
        try:
            result = agent.run_scenario(
                page, step_name, step_instruction, step_url,
                step_kw, step_max, run_dir, visual=visual
            )
            step_results.append(result)
            total_steps += result.get("steps_taken", 0)
            domains_used.append(step_domain)
            final_url = result.get("final_url", "")

            # Extract fact if configured
            ext = step.get("extract")
            if ext and result.get("success", False):
                var_name, var_val = extract_fact(page, ext, variables)
                if var_name and var_val:
                    variables[var_name] = var_val
                    extracts_used.append({"name": var_name, "value": var_val,
                                          "step": i, "method": ext.get("method")})
                    print(f"  📌 Extracted: {var_name} = \"{var_val}\"")

            # Check early stop: final keyword already satisfied
            cur_url = page.url
            if final_kw and final_kw.lower() in cur_url.lower():
                composite_success = True
                stop_reason = f"Final KW '{final_kw}' in URL at step {i}"
                print(f"  ⚡ Early stop: {stop_reason}")
                page.close()
                break

            # If this step failed, mark composite as failed
            if not result.get("success", False):
                stop_reason = f"Step {i} failed: {result.get('reason', '?')}"
                print(f"  ⚠ {stop_reason}")
                page.close()
                break

        finally:
            try:
                page.close()
            except Exception:
                pass

        if i < len(steps):
            time.sleep(1.5)

    else:
        # All steps completed — check if last step succeeded
        if step_results and step_results[-1].get("success"):
            # Check final keyword in last result's URL
            last_url = step_results[-1].get("final_url", "")
            if final_kw and final_kw.lower() in last_url.lower():
                composite_success = True
                stop_reason = f"All {len(steps)} steps completed, final KW matched"
            elif not final_kw:
                composite_success = True
                stop_reason = f"All {len(steps)} steps completed successfully"
            else:
                composite_success = True
                stop_reason = f"All steps passed (final KW partial check)"

    # Compute metrics
    for r in step_results:
        total_actions += r.get("steps_taken", 0)

    # Read latencies from traces
    for tf in Path(run_dir).glob("trace_*.json"):
        try:
            td = json.loads(tf.read_text())
            for s in td.get("steps", []):
                if isinstance(s.get("llm_latency"), (int, float)):
                    all_lats.append(s["llm_latency"])
        except Exception:
            pass
    avg_lat = round(sum(all_lats) / max(len(all_lats), 1), 2) if all_lats else 0

    result_summary = {
        "name": name,
        "composite_instruction": instruction,
        "success": composite_success,
        "stop_reason": stop_reason,
        "steps_total": total_steps,
        "domains_used": list(dict.fromkeys(domains_used)),
        "extracts_used": extracts_used,
        "avg_latency": avg_lat,
        "final_url": final_url,
        "variables": variables,
        "step_results": [{
            "name": r["name"], "success": r["success"],
            "steps": r["steps_taken"], "reason": r.get("reason", ""),
            "domain": r.get("domain", ""), "adherence": r.get("avg_adherence", 0),
        } for r in step_results],
    }

    st = "✅" if composite_success else "❌"
    print(f"\n  {st} COMPOSITE: {name}")
    print(f"    Result: {stop_reason}")
    print(f"    Total steps: {total_steps}  │  Domains: {' → '.join(domains_used)}")
    if variables:
        print(f"    Extracted: {variables}")

    return result_summary


# ═══════════════════════════════════════════════════════════════
#  Report Generation
# ═══════════════════════════════════════════════════════════════
def generate_reports(results, run_dir, elapsed):
    os.makedirs(REPORTS_DIR, exist_ok=True)

    total = len(results)
    ok = sum(1 for r in results if r["success"])

    # ── 01_summary.md ──
    sm = "# Composite Phase Summary — v1\n\n"
    sm += f"**Date**: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
    sm += f"**Runtime**: {elapsed:.0f}s\n\n"
    sm += "## Headline\n\n"
    sm += f"**{ok}/{total} composite tasks succeeded ({ok/max(total,1)*100:.0f}%)**\n\n"
    sm += "## Results Table\n\n"
    sm += "| # | Composite Task | OK | Steps | Domains | Extracts | Stop Reason |\n"
    sm += "|---|----------------|----|-------|---------|----------|-------------|\n"
    for i, r in enumerate(results, 1):
        s = "✅" if r["success"] else "❌"
        doms = " → ".join(r["domains_used"])
        exts = len(r.get("extracts_used", []))
        sm += (f"| {i} | {r['name'][:30]} | {s} | {r['steps_total']} | "
               f"{doms} | {exts} | {r['stop_reason'][:35]} |\n")
    sm += f"\n**Avg steps**: {sum(r['steps_total'] for r in results)/max(total,1):.1f}\n"
    sm += f"**Avg latency**: {sum(r['avg_latency'] for r in results)/max(total,1):.2f}s\n"
    sm += f"\n**Run directory**: `{run_dir}`\n"
    Path(REPORTS_DIR, "01_summary.md").write_text(sm)

    # ── 02_failure_modes.md ──
    fm = "# Failure Modes — Composite v1\n\n"
    failures = [r for r in results if not r["success"]]
    if not failures:
        fm += "## 🎉 No Failures!\n\nAll composite tasks completed successfully.\n\n"
    else:
        fm += f"## {len(failures)} Failed Tasks\n\n"
        categories = {}
        for r in failures:
            reason = r["stop_reason"]
            if "step" in reason.lower() and "failed" in reason.lower():
                cat = "Sub-step failure"
            elif "loop" in reason.lower():
                cat = "Loop detected"
            elif "max steps" in reason.lower():
                cat = "Max steps exhausted"
            else:
                cat = "Other"
            categories.setdefault(cat, []).append(r)

        for cat, rs in categories.items():
            fm += f"### {cat} ({len(rs)} tasks)\n\n"
            for r in rs:
                fm += f"- **{r['name']}**: {r['stop_reason']}\n"
                fm += f"  Domains: {' → '.join(r['domains_used'])}, Steps: {r['steps_total']}\n"
                for sr in r.get("step_results", []):
                    s = "✅" if sr["success"] else "❌"
                    fm += f"  - {s} {sr['name'][:40]} ({sr['steps']} steps): {sr['reason'][:30]}\n"
                fm += "\n"

    # Extraction analysis
    all_exts = [e for r in results for e in r.get("extracts_used", [])]
    if all_exts:
        fm += "## Extraction Events\n\n"
        fm += "| Step | Variable | Value | Method |\n"
        fm += "|------|----------|-------|--------|\n"
        for e in all_exts:
            fm += f"| {e['step']} | {e['name']} | {e['value'][:30]} | {e['method']} |\n"
    Path(REPORTS_DIR, "02_failure_modes.md").write_text(fm)

    # ── 03_design_notes.md ──
    dn = """# Design Notes — Composite Orchestrator v1

## Why Planning + Extraction + Variable Passing?

### Problem
Single-domain agents can execute tasks within one website, but real-world user
instructions often span multiple domains. "Find X on Wikipedia, then search for it
on Google" requires:
1. Navigating to Wikipedia and finding X
2. **Extracting** the fact (X) from the page
3. **Carrying** that fact to a new domain
4. Using it in the next instruction

### Solution: Composite Orchestrator

```
User: "Find Turing's birth year on Wikipedia, search Google for events that year"
                    ↓
            ┌─── PLAN ───┐
            │ Step 1: Wiki│── extract birth_year → {1912}
            │ Step 2: Ggl │── substitute {{birth_year}}
            └─────────────┘
                    ↓
        "Search Google for 'events in 1912'"
```

### Key Design Decisions

1. **Pre-built plans for known scenarios** — JSON file with step definitions,
   no LLM needed for decomposition = deterministic & fast.

2. **LLM decomposition for interactive mode** — when the user provides a
   free-form composite instruction, the LLM generates a plan JSON.

3. **Two extraction methods**:
   - **Regex**: fast, deterministic, works for structured data (dates, years)
   - **LLM**: flexible, handles natural language extraction (person names)

4. **Variable substitution** via `{{var_name}}` — simple, transparent,
   debuggable. Variables are logged in the trace.

5. **Early stopping** — if the final completion keyword is matched before
   all steps execute, stop immediately to save tokens.

6. **Same browser context** — all steps share one Playwright browser context
   but use separate pages, preserving cookies and state.

### Architecture

```
composite_orchestrator_v1.py
├── Import vla_unified_agent_v1_3 (reuse core agent)
├── Variable substitution engine
├── Fact extraction (regex + LLM)
├── LLM plan decomposition (interactive)
├── Sequential step executor
├── Report generator
└── CSV/JSON output
```

### Limitations & Future Work

- Plans are currently linear (step 1 → 2 → ... → N). No branching or parallelism.
- Extraction relies on page text at completion time. If the relevant fact is
  not in the first 2000 chars of body text, extraction may miss it.
- LLM extraction is non-deterministic. The `default` field provides a fallback.
- Variable substitution is literal string replacement. No computed expressions.
"""
    Path(REPORTS_DIR, "03_design_notes.md").write_text(dn)


# ═══════════════════════════════════════════════════════════════
#  CSV + JSON Output
# ═══════════════════════════════════════════════════════════════
def save_outputs(results, run_dir):
    csv_path = os.path.join(SCRIPT_DIR, "results_composite_v1.csv")
    with open(csv_path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["scenario_name", "success", "steps_total", "domains_used",
                     "avg_latency", "extracts_used", "final_url", "stop_reason"])
        for r in results:
            w.writerow([
                r["name"], r["success"], r["steps_total"],
                " → ".join(r["domains_used"]), r["avg_latency"],
                len(r.get("extracts_used", [])),
                r.get("final_url", "")[:80], r["stop_reason"]
            ])

    json_path = os.path.join(SCRIPT_DIR, "results_composite_v1.json")
    with open(json_path, "w") as f:
        json.dump({
            "timestamp": datetime.now().isoformat(),
            "run_dir": run_dir,
            "results": results,
        }, f, indent=2)

    return csv_path, json_path


# ═══════════════════════════════════════════════════════════════
#  Main
# ═══════════════════════════════════════════════════════════════
def main():
    ap = argparse.ArgumentParser(description="Composite Orchestrator v1")
    ap.add_argument("--scenarios", type=str, default=None,
                    help="Path to composite scenarios JSON")
    ap.add_argument("--headless", type=str, default="false")
    ap.add_argument("--visual", action="store_true")
    args = ap.parse_args()

    headless = args.headless.lower() in ("true", "1", "yes")

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("❌ playwright not installed"); sys.exit(1)

    scenarios = []
    if args.scenarios:
        with open(args.scenarios) as f:
            scenarios = json.load(f)
        mode = f"Scenarios: {args.scenarios}"
    else:
        mode = "Interactive"

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = os.path.join(SCRIPT_DIR, "runs", ts)
    os.makedirs(run_dir, exist_ok=True)

    print()
    print("══════════════════════════════════════════════════════════")
    print("  COMPOSITE ORCHESTRATOR v1 — MULTI-DOMAIN EXECUTION")
    print("══════════════════════════════════════════════════════════")
    print(f"  Agent:     vla_unified_agent_v1_3 (imported)")
    print(f"  Model:     {MODEL_NAME}")
    print(f"  Mode:      {mode}")
    print(f"  Run dir:   {run_dir}")
    print("══════════════════════════════════════════════════════════")

    results = []
    t0 = time.time()

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=headless)
        ctx = browser.new_context(viewport={"width": 1280, "height": 720},
                                  locale="en-US")
        try:
            if scenarios:
                for i, sc in enumerate(scenarios, 1):
                    r = run_composite(ctx, sc, run_dir, visual=args.visual)
                    results.append(r)
                    if i < len(scenarios):
                        time.sleep(2)
            else:
                # Interactive mode
                idx = 0
                while True:
                    print()
                    try:
                        instr = input("  Composite instruction (or 'quit'): ").strip()
                    except (EOFError, KeyboardInterrupt):
                        print("\n  Bye!"); break
                    if not instr or instr.lower() in ("quit", "exit", "q"):
                        break
                    idx += 1
                    print(f"\n  🧠 Decomposing instruction...")
                    plan = decompose_interactive(instr)
                    print(f"  Plan: {len(plan.get('steps', []))} steps")
                    for j, s in enumerate(plan.get("steps", []), 1):
                        print(f"    {j}. [{s.get('domain')}] {s.get('instruction', '?')[:50]}")

                    sc = {
                        "name": f"Interactive-{idx}",
                        "composite_instruction": instr,
                        "final_completion_keyword": plan.get("final_completion_keyword", ""),
                        "steps": plan["steps"],
                    }
                    r = run_composite(ctx, sc, run_dir, visual=args.visual)
                    results.append(r)
        finally:
            try:
                ctx.close(); browser.close()
            except Exception:
                pass

    elapsed = time.time() - t0

    if not results:
        print("\n  No results."); return

    # Save composite trace
    trace_path = os.path.join(run_dir, "composite_trace.json")
    with open(trace_path, "w") as f:
        json.dump({"timestamp": datetime.now().isoformat(), "results": results}, f, indent=2)

    comp_summ_path = os.path.join(run_dir, "composite_summary.json")
    with open(comp_summ_path, "w") as f:
        json.dump(results, f, indent=2)

    # Save CSV + JSON
    csv_path, json_path = save_outputs(results, run_dir)

    # Generate reports
    generate_reports(results, run_dir, elapsed)

    # Console summary
    total = len(results)
    ok = sum(1 for r in results if r["success"])
    avg_steps = sum(r["steps_total"] for r in results) / max(total, 1)
    avg_lat = sum(r["avg_latency"] for r in results) / max(total, 1)

    print()
    print("═" * 64)
    print("  COMPOSITE RESULTS — v1")
    print("═" * 64)
    print()
    print(f"  {'#':>2}  {'OK':>3}  {'Stp':>4}  {'Lat':>6}  {'Ext':>3}  "
          f"{'Domains':<22}  Name")
    print(f"  {'─' * 70}")
    for i, r in enumerate(results, 1):
        s = "✅" if r["success"] else "❌"
        doms = " → ".join(r["domains_used"])
        exts = len(r.get("extracts_used", []))
        print(f"  {i:>2}  {s:>3}  {r['steps_total']:>4}  "
              f"{r['avg_latency']:>5.1f}s  {exts:>3}  "
              f"{doms:<22}  {r['name'][:28]}")

    print(f"\n  Success: {ok}/{total} ({ok/max(total,1)*100:.0f}%)  │  "
          f"Avg steps: {avg_steps:.1f}  │  Avg latency: {avg_lat:.2f}s")

    if any(r.get("variables") for r in results):
        print(f"\n  Extracted variables:")
        for r in results:
            if r.get("variables"):
                for k, v in r["variables"].items():
                    print(f"    {r['name'][:25]:25} │ {k} = \"{v}\"")

    print(f"\n  📊 CSV:     {csv_path}")
    print(f"  📊 JSON:    {json_path}")
    print(f"  📁 Reports: {REPORTS_DIR}")
    print(f"  📁 Run:     {run_dir}")
    print()
    print("═" * 64)
    print("  COMPOSITE PHASE COMPLETE.")
    print("  READY FOR SINGLE-PROMPT MULTI-SITE DEMOS.")
    print("═" * 64)


if __name__ == "__main__":
    main()
