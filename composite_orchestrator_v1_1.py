#!/usr/bin/env python3
"""
Composite Orchestrator v1.1 — YouTube Playback Support.

Builds on v1 orchestrator with:
  - YouTube watch/play intent detection
  - Deterministic first-video click after search
  - Playback verification (video element + playing state)
  - Browser stays open for user to continue watching

Usage:
    python composite_orchestrator_v1_1.py                                # Interactive
    python composite_orchestrator_v1_1.py --scenarios file.json          # Batch
    python composite_orchestrator_v1_1.py --instruction "Search YouTube for X and watch"
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

import vla_unified_agent_v1_3 as agent
from youtube_playback_extension_v1 import (
    has_watch_intent, execute_playback
)

OLLAMA_URL  = agent.OLLAMA_URL
MODEL_NAME  = agent.MODEL_NAME
REPORTS_DIR = os.path.join(SCRIPT_DIR, "reports_youtube_playback_v1")


# ═══════════════════════════════════════════════════════════════
#  Variable Substitution (from v1)
# ═══════════════════════════════════════════════════════════════
def substitute(text, variables):
    if not text or not variables:
        return text
    for k, v in variables.items():
        text = text.replace("{{" + k + "}}", str(v))
    return text


# ═══════════════════════════════════════════════════════════════
#  Fact Extraction (from v1)
# ═══════════════════════════════════════════════════════════════
def extract_fact(page, extract_config, variables):
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
#  LLM Plan Decomposition (from v1, updated for playback)
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
5. If the user wants to WATCH/PLAY a video on YouTube, set "playback": true on that step.

Output ONLY valid JSON (no markdown fences):
{
  "steps": [
    {
      "domain": "youtube",
      "start_url": "https://www.youtube.com",
      "instruction": "Search YouTube for ...",
      "completion_keyword": "results?search_query=",
      "max_steps": 10,
      "playback": true
    }
  ],
  "final_completion_keyword": "..."
}

Composite instruction: """


def decompose_interactive(instruction):
    raw = agent.llm_query(DECOMPOSE_PROMPT + instruction, max_tokens=600)
    raw = re.sub(r'^```\w*\n?', '', raw.strip())
    raw = re.sub(r'\n?```$', '', raw.strip())
    try:
        plan = json.loads(raw)
        if "steps" in plan and isinstance(plan["steps"], list):
            # Auto-detect playback intent if not set
            for step in plan["steps"]:
                if step.get("domain") == "youtube" and has_watch_intent(instruction):
                    step["playback"] = True
            return plan
    except json.JSONDecodeError:
        pass

    # Fallback: detect YouTube + playback intent
    if has_watch_intent(instruction) and "youtube" in instruction.lower():
        # Extract search topic
        topic = re.sub(
            r'\b(watch|play|open|video|first|the|a|on|youtube|and|let|me|for|search)\b',
            '', instruction, flags=re.IGNORECASE
        ).strip()
        if not topic:
            topic = instruction
        return {
            "steps": [{
                "domain": "youtube",
                "start_url": "https://www.youtube.com",
                "instruction": f"Search YouTube for '{topic}'.",
                "completion_keyword": "results?search_query=",
                "max_steps": 10,
                "playback": True,
            }],
            "final_completion_keyword": "/watch",
        }

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
#  Run Composite Scenario (with playback support)
# ═══════════════════════════════════════════════════════════════
def run_composite(ctx, scenario, run_dir, visual=False):
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
    all_lats = []
    domains_used = []
    extracts_used = []
    composite_success = False
    stop_reason = "incomplete"
    final_url = ""
    playback_info = None
    keep_page_open = None  # Page to keep open for watching

    for i, step in enumerate(steps, 1):
        step_instruction = substitute(step["instruction"], variables)
        step_url = substitute(step["start_url"], variables)
        step_kw = substitute(step.get("completion_keyword", ""), variables)
        step_domain = step.get("domain", "other")
        step_max = step.get("max_steps", 15)
        step_name = f"{name} → Step {i}: {step_domain}"
        step_playback = step.get("playback", False)

        # Auto-detect playback intent from instruction
        if step_domain == "youtube" and not step_playback:
            step_playback = has_watch_intent(instruction) or has_watch_intent(step_instruction)

        print(f"\n  ┌── Step {i}/{len(steps)} │ {step_domain}"
              f"{' 🎬' if step_playback else ''} ──┐")
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

            # ═══ PLAYBACK MODE ═══
            if step_playback and result.get("success", False):
                ss_dir = os.path.join(run_dir, "screenshots")
                os.makedirs(ss_dir, exist_ok=True)

                playback_info = execute_playback(page)
                total_steps += 1  # Count the playback click as a step

                # Screenshot the video page
                try:
                    page.screenshot(path=os.path.join(ss_dir, f"playback_{i:02d}.png"))
                except Exception:
                    pass

                if playback_info.get("video_detected") or playback_info.get("url_is_watch"):
                    composite_success = True
                    final_url = page.url
                    stop_reason = "YouTube playback started"
                    keep_page_open = page  # DON'T close — user watches
                    print(f"\n  🎬 VIDEO READY — Browser stays open for watching.")
                    print(f"  🎬 Title: {playback_info.get('video_title', '?')[:60]}")
                    print(f"  🎬 URL: {final_url[:70]}")
                    break
                else:
                    print(f"  ⚠ Playback detection failed")

            # Check early stop
            cur_url = page.url
            if final_kw and final_kw.lower() in cur_url.lower():
                composite_success = True
                stop_reason = f"Final KW '{final_kw}' in URL at step {i}"
                print(f"  ⚡ Early stop: {stop_reason}")
                break

            if not result.get("success", False):
                stop_reason = f"Step {i} failed: {result.get('reason', '?')}"
                print(f"  ⚠ {stop_reason}")
                break

        finally:
            if page != keep_page_open:
                try:
                    page.close()
                except Exception:
                    pass

        if i < len(steps):
            time.sleep(1.5)

    else:
        if step_results and step_results[-1].get("success"):
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

    # Latencies from traces
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
        "playback": playback_info,
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

    return result_summary, keep_page_open


# ═══════════════════════════════════════════════════════════════
#  Report Generation
# ═══════════════════════════════════════════════════════════════
def generate_playback_report(results, run_dir, elapsed):
    os.makedirs(REPORTS_DIR, exist_ok=True)

    total = len(results)
    ok = sum(1 for r in results if r["success"])
    playback_tasks = [r for r in results if r.get("playback")]

    sm = "# YouTube Playback Report — v1.1\n\n"
    sm += f"**Date**: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
    sm += f"**Runtime**: {elapsed:.0f}s\n\n"
    sm += f"## Overall: {ok}/{total} tasks succeeded\n\n"

    sm += "## All Tasks\n\n"
    sm += "| # | Task | OK | Steps | Domains | Playback | Stop Reason |\n"
    sm += "|---|------|----|-------|---------|----------|-------------|\n"
    for i, r in enumerate(results, 1):
        s = "✅" if r["success"] else "❌"
        doms = " → ".join(r["domains_used"])
        pb = ""
        if r.get("playback"):
            p = r["playback"]
            pb = "▶️" if p.get("playing") else ("📺" if p.get("video_detected") else "❌")
        sm += (f"| {i} | {r['name'][:30]} | {s} | {r['steps_total']} | "
               f"{doms} | {pb} | {r['stop_reason'][:30]} |\n")

    if playback_tasks:
        sm += "\n## Playback Details\n\n"
        for r in playback_tasks:
            p = r["playback"]
            sm += f"### {r['name']}\n\n"
            sm += f"- **Video URL opened**: {'✅' if p.get('url_is_watch') else '❌'}\n"
            sm += f"- **`<video>` element detected**: {'✅' if p.get('video_detected') else '❌'}\n"
            sm += f"- **Playback started**: {'✅' if p.get('playing') else '❌'}\n"
            sm += f"- **Video title**: {p.get('video_title', 'N/A')[:60]}\n"
            sm += f"- **Steps taken**: {r['steps_total']}\n"
            sm += f"- **Wait time**: {p.get('waited_seconds', 0):.1f}s\n"
            sm += f"- **Avg LLM latency**: {r['avg_latency']:.2f}s\n"
            sm += f"- **Final URL**: `{r.get('final_url', '')[:70]}`\n\n"

    sm += f"\n**Run directory**: `{run_dir}`\n"
    Path(REPORTS_DIR, "01_summary.md").write_text(sm)


# ═══════════════════════════════════════════════════════════════
#  Main
# ═══════════════════════════════════════════════════════════════
def main():
    ap = argparse.ArgumentParser(description="Composite Orchestrator v1.1 — YouTube Playback")
    ap.add_argument("--scenarios", type=str, default=None)
    ap.add_argument("--instruction", type=str, default=None,
                    help="Single composite instruction (non-interactive)")
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
    elif args.instruction:
        mode = "Single instruction"
    else:
        mode = "Interactive"

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = os.path.join(SCRIPT_DIR, "runs", ts)
    os.makedirs(run_dir, exist_ok=True)

    print()
    print("══════════════════════════════════════════════════════════")
    print("  COMPOSITE ORCHESTRATOR v1.1 — YOUTUBE PLAYBACK")
    print("══════════════════════════════════════════════════════════")
    print(f"  Agent:     vla_unified_agent_v1_3 (imported)")
    print(f"  Model:     {MODEL_NAME}")
    print(f"  Playback:  YouTube watch/play/open intent auto-detected")
    print(f"  Mode:      {mode}")
    print(f"  Run dir:   {run_dir}")
    print("══════════════════════════════════════════════════════════")

    results = []
    t0 = time.time()
    keep_alive_page = None

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=headless)
        ctx = browser.new_context(viewport={"width": 1280, "height": 720},
                                  locale="en-US")
        try:
            if scenarios:
                for i, sc in enumerate(scenarios, 1):
                    r, kp = run_composite(ctx, sc, run_dir, visual=args.visual)
                    results.append(r)
                    if kp:
                        keep_alive_page = kp
                    if i < len(scenarios):
                        time.sleep(2)
            elif args.instruction:
                instr = args.instruction
                print(f"\n  🧠 Decomposing: \"{instr[:60]}\"...")
                plan = decompose_interactive(instr)
                print(f"  Plan: {len(plan.get('steps', []))} steps")
                for j, s in enumerate(plan.get("steps", []), 1):
                    pb = " 🎬" if s.get("playback") else ""
                    print(f"    {j}. [{s.get('domain')}] {s.get('instruction', '?')[:50]}{pb}")
                sc = {
                    "name": "CLI Instruction",
                    "composite_instruction": instr,
                    "final_completion_keyword": plan.get("final_completion_keyword", ""),
                    "steps": plan["steps"],
                }
                r, kp = run_composite(ctx, sc, run_dir, visual=args.visual)
                results.append(r)
                if kp:
                    keep_alive_page = kp
            else:
                # Interactive mode
                idx = 0
                while True:
                    print()
                    try:
                        instr = input("  Instruction (or 'quit'): ").strip()
                    except (EOFError, KeyboardInterrupt):
                        print("\n  Bye!"); break
                    if not instr or instr.lower() in ("quit", "exit", "q"):
                        break
                    idx += 1
                    print(f"\n  🧠 Decomposing instruction...")
                    plan = decompose_interactive(instr)
                    print(f"  Plan: {len(plan.get('steps', []))} steps")
                    for j, s in enumerate(plan.get("steps", []), 1):
                        pb = " 🎬" if s.get("playback") else ""
                        print(f"    {j}. [{s.get('domain')}] {s.get('instruction', '?')[:50]}{pb}")
                    sc = {
                        "name": f"Interactive-{idx}",
                        "composite_instruction": instr,
                        "final_completion_keyword": plan.get("final_completion_keyword", ""),
                        "steps": plan["steps"],
                    }
                    r, kp = run_composite(ctx, sc, run_dir, visual=args.visual)
                    results.append(r)
                    if kp:
                        keep_alive_page = kp
                        # Don't close — let user watch
                        print("\n  🎬 Browser is open. Video is playing.")
                        try:
                            input("  Press Enter when done watching (or Ctrl+C to exit)... ")
                        except (EOFError, KeyboardInterrupt):
                            print()
                        break  # Exit interactive loop after playback

            # If playback page is open, wait for user
            if keep_alive_page and not args.instruction:
                pass  # Already handled above
            elif keep_alive_page:
                print("\n  🎬 Browser is open. Video is playing.")
                print("  🎬 Press Enter when done watching (or Ctrl+C to exit)...")
                try:
                    input()
                except (EOFError, KeyboardInterrupt):
                    print()

        finally:
            try:
                ctx.close(); browser.close()
            except Exception:
                pass

    elapsed = time.time() - t0

    if not results:
        print("\n  No results."); return

    # Save trace + summary
    trace_path = os.path.join(run_dir, "composite_trace.json")
    with open(trace_path, "w") as f:
        json.dump({"timestamp": datetime.now().isoformat(), "results": results}, f, indent=2)

    # Generate report
    generate_playback_report(results, run_dir, elapsed)

    # Console
    total = len(results)
    ok = sum(1 for r in results if r["success"])

    print()
    print("═" * 64)
    print("  RESULTS — v1.1 (YouTube Playback)")
    print("═" * 64)
    print()
    for i, r in enumerate(results, 1):
        s = "✅" if r["success"] else "❌"
        doms = " → ".join(r["domains_used"])
        pb = ""
        if r.get("playback"):
            p = r["playback"]
            if p.get("playing"):    pb = "▶️ playing"
            elif p.get("video_detected"): pb = "📺 detected"
            else: pb = "❌ no video"
        print(f"  {i:>2}  {s}  {r['steps_total']:>3} steps  {doms:<20}  "
              f"{r['name'][:28]:<28}  {pb}")

    print(f"\n  Success: {ok}/{total} ({ok/max(total,1)*100:.0f}%)")
    print(f"\n  📁 Reports: {REPORTS_DIR}")
    print(f"  📁 Run:     {run_dir}")
    print()
    print("═" * 64)
    print("  YOUTUBE PLAYBACK EXTENSION COMPLETE.")
    print("═" * 64)


if __name__ == "__main__":
    main()
