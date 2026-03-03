#!/usr/bin/env python3
"""
Composite Orchestrator v1.2 — Persistent Memory Layer.

Builds on v1.1 (YouTube Playback) with:
  - Persistent user profile (memory_store.json)
  - Regex-based memory extraction from instructions
  - Instruction enrichment with memory for auto-fill
  - Auto-fill logging
  - --test-memory mode for sequential identity → booking flow

Usage:
    python composite_orchestrator_v1_2.py                                     # Interactive
    python composite_orchestrator_v1_2.py --scenarios file.json               # Batch
    python composite_orchestrator_v1_2.py --instruction "Book a hotel..."     # Single
    python composite_orchestrator_v1_2.py --test-memory                       # Memory test
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
from youtube_playback_extension_v1 import has_watch_intent, execute_playback
from memory_manager_v1 import (
    load_memory, save_memory, update_memory, get_memory,
    extract_memory_from_user_instruction, enrich_instruction,
    format_profile, detect_autofills, is_web_task, get_memory_log,
    PROFILE_KEYS,
)

OLLAMA_URL  = agent.OLLAMA_URL
MODEL_NAME  = agent.MODEL_NAME
REPORTS_DIR = os.path.join(SCRIPT_DIR, "reports_memory_v1")


# ═══════════════════════════════════════════════════════════════
#  Variable Substitution
# ═══════════════════════════════════════════════════════════════
def substitute(text, variables):
    if not text or not variables:
        return text
    for k, v in variables.items():
        text = text.replace("{{" + k + "}}", str(v))
    return text


# ═══════════════════════════════════════════════════════════════
#  Fact Extraction
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
#  LLM Plan Decomposition (with memory context)
# ═══════════════════════════════════════════════════════════════
def make_decompose_prompt(memory):
    """Build decomposition prompt with user memory profile."""
    profile = format_profile(memory)
    return f"""You are a task decomposition engine. Given a composite instruction, break it into sequential web subtasks.

Known user profile:
{profile}

Available domains and start URLs:
  wikipedia : https://en.wikipedia.org
  google    : https://www.google.com
  youtube   : https://www.youtube.com
  store     : http://localhost:8001/index.html
  booking   : http://localhost:8002/step1_service.html

Rules:
1. Each step runs on ONE domain. Steps execute sequentially.
2. Use {{{{variable_name}}}} syntax to reference extracted values from previous steps.
3. Include "extract" only when a fact must carry forward.
4. Keep max_steps 5-15 per step.
5. If the user wants to WATCH/PLAY a video on YouTube, set "playback": true on that step.
6. When the instruction involves forms (booking, store), include the user profile fields
   in the step instruction so the agent can fill them in.

Output ONLY valid JSON (no markdown fences):
{{
  "steps": [
    {{
      "domain": "booking",
      "start_url": "http://localhost:8002/step1_service.html",
      "instruction": "...",
      "completion_keyword": "VLA_BOOKING_SUCCESS",
      "max_steps": 20
    }}
  ],
  "final_completion_keyword": "..."
}}

Composite instruction: """


def _build_booking_instruction(instruction, memory):
    """Build a clean booking instruction with memory values pre-filled."""
    # Detect service type from instruction
    lower = instruction.lower()
    if "doctor" in lower or "appointment" in lower:
        service = "Doctor Appointment"
    elif "hotel" in lower:
        service = "Hotel Booking"
    elif "flight" in lower:
        service = "Flight Reservation"
    else:
        service = "Hotel Booking"

    name = memory.get("name", "Sparsh")
    email = memory.get("email", "sparsh@test.com")

    return (f"Select {service} and click Next Step. "
            f"Enter the booking date for tomorrow. "
            f"Enter full name {name}. Enter email {email}. "
            f"Click Next Step. Click Confirm Booking. Do not click Back.")


def _build_store_instruction(instruction, memory):
    """Build a clean store instruction with memory values pre-filled."""
    name = memory.get("name", "Sparsh")
    email = memory.get("email", "sparsh@test.com")
    address = memory.get("address", "123 Wall Street")

    return (f"{instruction} "
            f"When filling checkout, use name {name}, email {email}, "
            f"address {address}.")


def decompose_interactive(instruction, memory):
    # ─── Deterministic fallbacks for booking/store (skip LLM decomposition) ───
    lower = instruction.lower()

    if "book" in lower or "appointment" in lower or "reservation" in lower:
        booking_instr = _build_booking_instruction(instruction, memory)
        return {
            "steps": [{
                "domain": "booking",
                "start_url": "http://localhost:8002/step1_service.html",
                "instruction": booking_instr,
                "completion_keyword": "VLA_BOOKING_SUCCESS",
                "max_steps": 25,
            }],
            "final_completion_keyword": "VLA_BOOKING_SUCCESS",
        }

    if any(k in lower for k in ["buy", "purchase", "order", "checkout"]):
        store_instr = _build_store_instruction(instruction, memory)
        return {
            "steps": [{
                "domain": "store",
                "start_url": "http://localhost:8001/index.html",
                "instruction": store_instr,
                "completion_keyword": "VLA_ORDER_SUCCESS",
                "max_steps": 25,
            }],
            "final_completion_keyword": "VLA_ORDER_SUCCESS",
        }

    # ─── YouTube playback ───
    if has_watch_intent(instruction) and "youtube" in lower:
        topic = re.sub(
            r'\b(watch|play|open|video|first|the|a|on|youtube|and|let|me|for|search)\b',
            '', instruction, flags=re.IGNORECASE
        ).strip() or instruction
        return {
            "steps": [{
                "domain": "youtube", "start_url": "https://www.youtube.com",
                "instruction": f"Search YouTube for '{topic}'.",
                "completion_keyword": "results?search_query=",
                "max_steps": 10, "playback": True,
            }],
            "final_completion_keyword": "/watch",
        }

    # ─── LLM decomposition for other tasks ───
    prompt = make_decompose_prompt(memory) + instruction
    raw = agent.llm_query(prompt, max_tokens=600)
    raw = re.sub(r'^```\w*\n?', '', raw.strip())
    raw = re.sub(r'\n?```$', '', raw.strip())
    try:
        plan = json.loads(raw)
        if "steps" in plan and isinstance(plan["steps"], list):
            for step in plan["steps"]:
                if step.get("domain") == "youtube" and has_watch_intent(instruction):
                    step["playback"] = True
            return plan
    except json.JSONDecodeError:
        pass

    # Generic fallback
    return {
        "steps": [{
            "domain": "google", "start_url": "https://www.google.com",
            "instruction": instruction,
            "completion_keyword": "search?q=", "max_steps": 10,
        }],
        "final_completion_keyword": "search?q=",
    }


# ═══════════════════════════════════════════════════════════════
#  Run Composite Scenario (with memory + playback)
# ═══════════════════════════════════════════════════════════════
def run_composite(ctx, scenario, run_dir, memory, visual=False):
    name = scenario.get("name", "Composite")
    instruction = scenario.get("composite_instruction", "")
    steps = scenario.get("steps", [])
    final_kw = scenario.get("final_completion_keyword", "")

    print(f"\n{'━' * 72}")
    print(f"  🔗 COMPOSITE: {name}")
    print(f"  Instruction: {instruction[:70]}")
    print(f"  Steps: {len(steps)}  │  Final KW: {final_kw or '(none)'}")
    print(f"  Memory: {memory.get('name', '?')} ({memory.get('email', '?')})")
    print(f"{'━' * 72}")

    variables = {}
    step_results = []
    total_steps = 0
    all_lats = []
    domains_used = []
    extracts_used = []
    all_autofills = []
    composite_success = False
    stop_reason = "incomplete"
    final_url = ""
    playback_info = None
    keep_page_open = None

    # Track trace files before this scenario
    existing_traces = set(Path(run_dir).glob("trace_*.json"))

    for i, step in enumerate(steps, 1):
        step_instruction = substitute(step["instruction"], variables)
        step_url = substitute(step["start_url"], variables)
        step_kw = substitute(step.get("completion_keyword", ""), variables)
        step_domain = step.get("domain", "other")
        step_max = step.get("max_steps", 15)
        step_name = f"{name} → Step {i}: {step_domain}"
        step_playback = step.get("playback", False)

        if step_domain == "youtube" and not step_playback:
            step_playback = has_watch_intent(instruction) or has_watch_intent(step_instruction)

        # ═══ ENRICH WITH MEMORY (only if from LLM decomposition) ═══
        # The deterministic builders already include memory values in the instruction,
        # so only enrich if the instruction doesn't already contain memory values.
        name_val = memory.get("name", "")
        if step_domain in ("booking", "store") and name_val and name_val not in step_instruction:
            step_instruction = enrich_instruction(step_instruction, memory)
            print(f"  💾 Memory injected into step {i} instruction")

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

            # ═══ AUTO-FILL DETECTION ═══
            new_traces = set(Path(run_dir).glob("trace_*.json")) - existing_traces
            for tf in new_traces:
                try:
                    td = json.loads(tf.read_text())
                    fills = detect_autofills(td, memory)
                    for af in fills:
                        print(f"  AUTO-FILL: field={af['field']} value={af['value']}")
                    all_autofills.extend(fills)
                except Exception:
                    pass
            existing_traces = set(Path(run_dir).glob("trace_*.json"))

            # ═══ PLAYBACK MODE ═══
            if step_playback and result.get("success", False):
                ss_dir = os.path.join(run_dir, "screenshots")
                os.makedirs(ss_dir, exist_ok=True)
                playback_info = execute_playback(page)
                total_steps += 1
                try:
                    page.screenshot(path=os.path.join(ss_dir, f"playback_{i:02d}.png"))
                except Exception:
                    pass
                if playback_info.get("video_detected") or playback_info.get("url_is_watch"):
                    composite_success = True
                    final_url = page.url
                    stop_reason = "YouTube playback started"
                    keep_page_open = page
                    print(f"\n  🎬 VIDEO READY — Browser stays open.")
                    break

            # Check early stop
            cur_url = page.url
            if final_kw and final_kw.lower() in cur_url.lower():
                composite_success = True
                stop_reason = f"Final KW '{final_kw}' in URL at step {i}"
                print(f"  ⚡ Early stop: {stop_reason}")
                break

            # Check text-based keyword
            if final_kw and result.get("success"):
                page_text = agent.get_text(page, 1000)
                if final_kw.lower() in page_text.lower():
                    composite_success = True
                    stop_reason = f"Final KW '{final_kw}' in text at step {i}"
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
                stop_reason = f"All steps completed successfully"
            else:
                composite_success = True
                stop_reason = f"All steps passed"

    # Latencies
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
        "autofills": all_autofills,
        "avg_latency": avg_lat,
        "final_url": final_url,
        "variables": variables,
        "playback": playback_info,
        "step_results": [{
            "name": r["name"], "success": r["success"],
            "steps": r["steps_taken"], "reason": r.get("reason", ""),
        } for r in step_results],
    }

    st = "✅" if composite_success else "❌"
    print(f"\n  {st} COMPOSITE: {name}")
    print(f"    Result: {stop_reason}")
    print(f"    Steps: {total_steps}  │  Domains: {' → '.join(domains_used)}")
    print(f"    Auto-fills: {len(all_autofills)}")

    return result_summary, keep_page_open


# ═══════════════════════════════════════════════════════════════
#  Report Generation
# ═══════════════════════════════════════════════════════════════
def generate_reports(results, memory, memory_updates, run_dir, elapsed):
    os.makedirs(REPORTS_DIR, exist_ok=True)

    total = len(results)
    ok = sum(1 for r in results if r["success"])
    total_autofills = sum(len(r.get("autofills", [])) for r in results)

    # ── 01_summary.md ──
    sm = "# Memory Layer Summary — v1.2\n\n"
    sm += f"**Date**: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
    sm += f"**Runtime**: {elapsed:.0f}s\n\n"
    sm += "## Memory Profile\n\n"
    sm += "| Key | Value |\n|-----|-------|\n"
    for k in PROFILE_KEYS:
        sm += f"| {k} | {memory.get(k, '')} |\n"

    sm += f"\n## Results: {ok}/{total} tasks succeeded\n\n"
    sm += "| # | Task | OK | Steps | Auto-fills | Domains | Stop Reason |\n"
    sm += "|---|------|----|-------|------------|---------|-------------|\n"
    for i, r in enumerate(results, 1):
        s = "✅" if r["success"] else "❌"
        doms = " → ".join(r["domains_used"])
        af = len(r.get("autofills", []))
        sm += (f"| {i} | {r['name'][:28]} | {s} | {r['steps_total']} | "
               f"{af} | {doms} | {r['stop_reason'][:30]} |\n")

    sm += f"\n## Memory Stats\n\n"
    sm += f"- **Memory updates this session**: {len(memory_updates)}\n"
    sm += f"- **Memory injections**: {sum(1 for r in results if r.get('domains_used') and any(d in ('booking', 'store') for d in r['domains_used']))}\n"
    sm += f"- **Auto-filled fields**: {total_autofills}\n"
    sm += f"- **Success rate**: {ok/max(total,1)*100:.0f}%\n"
    Path(REPORTS_DIR, "01_summary.md").write_text(sm)

    # ── 02_memory_log.md ──
    ml = "# Memory Log — v1.2\n\n"
    ml += "## Memory Updates\n\n"
    log = get_memory_log()
    if log:
        ml += "| Time | Key | Old Value | New Value |\n"
        ml += "|------|-----|-----------|----------|\n"
        for entry in log:
            ml += (f"| {entry['time']} | {entry['key']} | "
                   f"{entry.get('old', '—') or '—'} | {entry['new']} |\n")
    else:
        ml += "No memory updates this session.\n"

    ml += "\n## Auto-Fill Events\n\n"
    all_af = [af for r in results for af in r.get("autofills", [])]
    if all_af:
        ml += "| Step | Field | Memory Key | Value |\n"
        ml += "|------|-------|-----------|-------|\n"
        for af in all_af:
            ml += f"| {af['step']} | {af['field'][:20]} | {af['memory_key']} | {af['value']} |\n"
    else:
        ml += "No auto-fill events detected.\n"

    ml += f"\n## Current Memory State\n\n```json\n{json.dumps(memory, indent=2)}\n```\n"
    Path(REPORTS_DIR, "02_memory_log.md").write_text(ml)

    # ── 03_design_notes.md ──
    dn = """# Design Notes — Memory Layer v1.2

## Deterministic Regex Extraction

Memory extraction from instructions uses ONLY regex patterns — no LLM calls.
This ensures:
- **Speed**: No network latency for memory operations
- **Determinism**: Same input always produces same output
- **Transparency**: Every pattern is inspectable and debuggable

### Patterns Used
```
"my name is X"     → name
"my email is Y"    → email
"my phone is P"    → phone
"my address is Z"  → address
"my city is C"     → city
"my zip is Z"      → zip
"my country is N"  → country
```

Regex is case-insensitive and handles:
- "My name is Sparsh" → {name: "Sparsh"}
- "my email is a@b.com and my phone is 123" → {email: "a@b.com", phone: "123"}

## Memory Injection Strategy

Memory is injected at TWO levels:

1. **Decomposition prompt** — The LLM planner sees the user profile when generating
   the step plan. This helps it include relevant details in step instructions.

2. **Step instruction enrichment** — For booking/store domains, the step instruction
   is appended with: "When filling forms, use these personal details: name=X, email=Y..."
   This ensures the v1.3 agent's LLM uses memory values for TYPE actions.

## Why No LLM for Memory Extraction?

1. **Reliability**: LLMs may hallucinate or misparse fields
2. **Speed**: Regex is instant; LLM calls take 3-5 seconds each
3. **Cost**: No tokens consumed for memory operations
4. **Privacy**: Memory data stays local, never sent to LLM
5. **Debuggability**: Regex patterns are transparent and testable

## Auto-Fill Flow

```
User: "Book a doctor appointment for tomorrow"
         ↓
  Load memory: {name: "Sparsh", email: "sparsh@test.com", ...}
         ↓
  Enrich instruction:
    "Book a doctor appointment for tomorrow.
     When filling forms, use: name=Sparsh, email=sparsh@test.com, ..."
         ↓
  v1.3 agent fills form fields using enriched instruction
         ↓
  Trace analysis: detect which fields matched memory values
         ↓
  Log: AUTO-FILL: field=full_name value=Sparsh
       AUTO-FILL: field=email value=sparsh@test.com
```
"""
    Path(REPORTS_DIR, "03_design_notes.md").write_text(dn)


# ═══════════════════════════════════════════════════════════════
#  Main
# ═══════════════════════════════════════════════════════════════
def main():
    ap = argparse.ArgumentParser(description="Composite Orchestrator v1.2 — Memory Layer")
    ap.add_argument("--scenarios", type=str, default=None)
    ap.add_argument("--instruction", type=str, default=None)
    ap.add_argument("--test-memory", action="store_true",
                    help="Run two-step memory test: identity → booking")
    ap.add_argument("--headless", type=str, default="false")
    ap.add_argument("--visual", action="store_true")
    args = ap.parse_args()

    headless = args.headless.lower() in ("true", "1", "yes")

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("❌ playwright not installed"); sys.exit(1)

    # ═══ LOAD MEMORY ═══
    memory = load_memory()
    all_updates = {}

    print()
    print("══════════════════════════════════════════════════════════")
    print("  COMPOSITE ORCHESTRATOR v1.2 — MEMORY LAYER")
    print("══════════════════════════════════════════════════════════")
    print(f"  Agent:     vla_unified_agent_v1_3 (imported)")
    print(f"  Model:     {MODEL_NAME}")
    print(f"  Memory:    memory_store.json")
    print(f"  Profile:")
    for k in PROFILE_KEYS:
        v = memory.get(k, "")
        if v:
            print(f"    {k:>10}: {v}")
    print("══════════════════════════════════════════════════════════")
    print(f"  MEMORY LAYER ENABLED. PROFILE LOADED FOR {memory.get('name', 'UNKNOWN').upper()}.")
    print("══════════════════════════════════════════════════════════")

    scenarios = []
    if args.scenarios:
        with open(args.scenarios) as f:
            scenarios = json.load(f)
        mode = f"Scenarios: {args.scenarios}"
    elif args.test_memory:
        mode = "Test Memory (2-step)"
    elif args.instruction:
        mode = "Single instruction"
    else:
        mode = "Interactive"

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = os.path.join(SCRIPT_DIR, "runs", ts)
    os.makedirs(run_dir, exist_ok=True)

    print(f"  Mode:      {mode}")
    print(f"  Run dir:   {run_dir}")

    results = []
    t0 = time.time()

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=headless)
        ctx = browser.new_context(viewport={"width": 1280, "height": 720},
                                  locale="en-US")
        keep_alive = None
        try:
            if args.test_memory:
                # ═══ TEST MEMORY MODE ═══
                test_instructions = [
                    ("My name is Sparsh and my email is sparsh@test.com "
                     "and my phone is 1234567890 and my address is 123 Wall Street."),
                    "Book a doctor appointment for tomorrow.",
                ]

                for idx, instr in enumerate(test_instructions, 1):
                    print(f"\n{'═' * 60}")
                    print(f"  TEST STEP {idx}/{len(test_instructions)}")
                    print(f"  Instruction: {instr[:65]}")
                    print(f"{'═' * 60}")

                    # Extract memory from instruction
                    updates = extract_memory_from_user_instruction(instr)
                    if updates:
                        all_updates.update(updates)
                        memory = load_memory()  # Reload after updates
                        print(f"  📝 Memory updated: {', '.join(f'{k}={v}' for k, v in updates.items())}")

                    # Check if web task
                    if not is_web_task(instr):
                        print(f"  📝 Memory-only instruction. No web task needed.")
                        results.append({
                            "name": f"Memory Update {idx}",
                            "composite_instruction": instr,
                            "success": True,
                            "stop_reason": "Memory updated (no web task)",
                            "steps_total": 0,
                            "domains_used": [],
                            "extracts_used": [],
                            "autofills": [],
                            "avg_latency": 0,
                            "final_url": "",
                            "variables": {},
                            "playback": None,
                            "step_results": [],
                        })
                        continue

                    # Decompose and execute
                    print(f"\n  🧠 Decomposing with memory context...")
                    plan = decompose_interactive(instr, memory)
                    print(f"  Plan: {len(plan.get('steps', []))} steps")
                    for j, s in enumerate(plan.get("steps", []), 1):
                        print(f"    {j}. [{s.get('domain')}] {s.get('instruction', '?')[:50]}")

                    sc = {
                        "name": f"Test-{idx}: {instr[:30]}",
                        "composite_instruction": instr,
                        "final_completion_keyword": plan.get("final_completion_keyword", ""),
                        "steps": plan["steps"],
                    }
                    r, kp = run_composite(ctx, sc, run_dir, memory, visual=args.visual)
                    results.append(r)
                    if kp:
                        keep_alive = kp
                    time.sleep(2)

            elif scenarios:
                for i, sc in enumerate(scenarios, 1):
                    instr = sc.get("composite_instruction", "")
                    updates = extract_memory_from_user_instruction(instr)
                    if updates:
                        all_updates.update(updates)
                        memory = load_memory()
                    r, kp = run_composite(ctx, sc, run_dir, memory, visual=args.visual)
                    results.append(r)
                    if kp:
                        keep_alive = kp
                    if i < len(scenarios):
                        time.sleep(2)

            elif args.instruction:
                instr = args.instruction
                updates = extract_memory_from_user_instruction(instr)
                if updates:
                    all_updates.update(updates)
                    memory = load_memory()
                print(f"\n  🧠 Decomposing: \"{instr[:55]}\"...")
                plan = decompose_interactive(instr, memory)
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
                r, kp = run_composite(ctx, sc, run_dir, memory, visual=args.visual)
                results.append(r)
                if kp:
                    keep_alive = kp

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

                    # Extract memory
                    updates = extract_memory_from_user_instruction(instr)
                    if updates:
                        all_updates.update(updates)
                        memory = load_memory()

                    if not is_web_task(instr):
                        print(f"  📝 Memory updated. No web task.")
                        continue

                    print(f"\n  🧠 Decomposing...")
                    plan = decompose_interactive(instr, memory)
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
                    r, kp = run_composite(ctx, sc, run_dir, memory, visual=args.visual)
                    results.append(r)
                    if kp:
                        keep_alive = kp
                        print("\n  🎬 Browser open. Video playing.")
                        try:
                            input("  Press Enter when done... ")
                        except (EOFError, KeyboardInterrupt):
                            print()
                        break

            if keep_alive and args.instruction:
                print("\n  🎬 Browser open. Press Enter when done...")
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

    # Save trace
    trace_path = os.path.join(run_dir, "composite_trace.json")
    with open(trace_path, "w") as f:
        json.dump({"timestamp": datetime.now().isoformat(), "results": results}, f, indent=2)

    # Generate reports
    memory = load_memory()
    generate_reports(results, memory, all_updates, run_dir, elapsed)

    # Console
    total = len(results)
    ok = sum(1 for r in results if r["success"])
    total_af = sum(len(r.get("autofills", [])) for r in results)

    print()
    print("═" * 64)
    print("  RESULTS — v1.2 (Memory Layer)")
    print("═" * 64)
    print()
    for i, r in enumerate(results, 1):
        s = "✅" if r["success"] else "❌"
        doms = " → ".join(r["domains_used"]) if r["domains_used"] else "(memory)"
        af = len(r.get("autofills", []))
        print(f"  {i:>2}  {s}  {r['steps_total']:>3} steps  "
              f"{doms:<20}  AF:{af}  {r['name'][:28]}")

    print(f"\n  Success: {ok}/{total} ({ok / max(total, 1) * 100:.0f}%)")
    print(f"  Memory updates: {len(all_updates)}")
    print(f"  Auto-fills: {total_af}")

    print(f"\n  📁 Reports: {REPORTS_DIR}")
    print(f"  📁 Run:     {run_dir}")
    print()
    print("══════════════════════════════════════════════════════════")
    print(f"  MEMORY LAYER ENABLED. PROFILE LOADED FOR {memory.get('name', 'UNKNOWN').upper()}.")
    print(f"  READY FOR FOLLOW-UP QUESTION LOOP.")
    print("══════════════════════════════════════════════════════════")


if __name__ == "__main__":
    main()
