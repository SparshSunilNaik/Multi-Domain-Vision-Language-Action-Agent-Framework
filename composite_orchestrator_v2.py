#!/usr/bin/env python3
"""
Composite Orchestrator v2 — Schema-Safe, Extraction-Verified, Memory-Integrated.

Builds on v1.1 orchestrator with:
  - Standardized StepResult schema (no raw .get() on unknown types)
  - Extraction verification with regex validators
  - Single-retry fallback strategy per step
  - Memory integration via memory_store.json
  - Plan → Execute → Verify loop

Usage:
    python composite_orchestrator_v2.py --instruction "..."
    python composite_orchestrator_v2.py --scenarios composite_scenarios_v2.json
"""

import argparse
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

try:
    from youtube_playback_extension_v1 import has_watch_intent, execute_playback
except ImportError:
    def has_watch_intent(_): return False
    def execute_playback(_): return {}

MODEL_NAME = agent.MODEL_NAME
MEMORY_FILE = os.path.join(SCRIPT_DIR, "memory_store.json")
REPORTS_DIR = os.path.join(SCRIPT_DIR, "reports_composite_v2")


# ═══════════════════════════════════════════════════════════════
#  1) RESULT NORMALIZER — StepResult Schema
# ═══════════════════════════════════════════════════════════════

class StepResult:
    """Standardized result container. Eliminates raw .get() on unknown types."""

    __slots__ = ("ok", "value", "reason", "meta")

    def __init__(self, ok=False, value=None, reason="", meta=None):
        self.ok = bool(ok)
        self.value = value
        self.reason = str(reason) if reason else ""
        self.meta = dict(meta) if meta else {}

    def to_dict(self):
        return {
            "ok": self.ok,
            "value": self.value,
            "reason": self.reason,
            "meta": self.meta,
        }

    def __repr__(self):
        st = "✅" if self.ok else "❌"
        val = f'"{self.value}"' if self.value else "None"
        return f"StepResult({st}, value={val}, reason={self.reason[:40]})"


def normalize_result(raw):
    """Convert any agent return value into a safe StepResult.

    Handles:
      - dict with 'success'/'ok' key  → StepResult
      - str                           → StepResult(ok=True, value=str)
      - None                          → StepResult(ok=False)
      - StepResult                    → passthrough
    """
    if isinstance(raw, StepResult):
        return raw
    if raw is None:
        return StepResult(ok=False, reason="Step returned None")
    if isinstance(raw, str):
        return StepResult(ok=bool(raw.strip()), value=raw.strip(),
                          reason="String result")
    if isinstance(raw, dict):
        ok = raw.get("ok", raw.get("success", False))
        value = raw.get("value", raw.get("final_url", None))
        reason = raw.get("reason", raw.get("stop_reason", ""))
        meta = {k: v for k, v in raw.items()
                if k not in ("ok", "success", "value", "reason")}
        return StepResult(ok=bool(ok), value=value, reason=str(reason), meta=meta)
    # Unknown type — treat as failure
    return StepResult(ok=False, reason=f"Unknown result type: {type(raw).__name__}")


# ═══════════════════════════════════════════════════════════════
#  2) EXTRACTION VERIFIER — Validators + Single Retry
# ═══════════════════════════════════════════════════════════════

VALIDATORS = {
    "year": re.compile(r"\b(1[0-9]{3}|20[0-9]{2})\b"),
    "name": re.compile(r"[A-Z][a-z]+\s+[A-Z][a-z]+"),
    "url":  re.compile(r"https?://\S+"),
}


def detect_value_type(name, value):
    """Auto-detect what kind of value we expect based on variable name."""
    n = name.lower()
    if any(k in n for k in ("year", "date", "born", "founded")):
        return "year"
    if any(k in n for k in ("name", "creator", "author", "founder", "inventor",
                             "person", "who")):
        return "name"
    if any(k in n for k in ("url", "link", "href")):
        return "url"
    return "any"


def validate_extraction(var_name, value):
    """Validate an extracted value. Returns (is_valid, cleaned_value, reason)."""
    if not value or not str(value).strip():
        return False, None, "Empty extraction"

    value = str(value).strip()
    vtype = detect_value_type(var_name, value)

    if vtype == "any":
        return True, value, "Non-empty value accepted"

    validator = VALIDATORS.get(vtype)
    if not validator:
        return True, value, f"No validator for type '{vtype}'"

    m = validator.search(value)
    if m:
        cleaned = m.group(0) if vtype != "year" else m.group(1)
        return True, cleaned, f"Validated as {vtype}: {cleaned}"

    return False, value, f"Failed {vtype} validation: '{value[:40]}'"


def retry_extraction(page, var_name, extract_config, original_value):
    """Single fallback retry for failed extraction.

    Strategies tried in order:
      1. Infobox scan (Wikipedia)
      2. Page text keyword scan
      3. LLM re-extraction with tighter prompt
    """
    text = agent.get_text(page, 3000)
    vtype = detect_value_type(var_name, original_value or "")

    # Strategy 1: Infobox extraction (Wikipedia pattern)
    if vtype == "name":
        # Look for "Created by X" or "Designed by X" or "Developer X" patterns
        for pat in [r"(?:Created|Designed|Developed|Invented|Founded)\s+by\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)",
                    r"(?:creator|author|designer|developer|inventor|founder)\s*[:=]\s*([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)"]:
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                val = m.group(1).strip()
                ok, cleaned, reason = validate_extraction(var_name, val)
                if ok:
                    return True, cleaned, f"Retry infobox: {reason}"

    if vtype == "year":
        for pat in [r"(?:born|founded|created|released|established)\s+(?:in\s+)?(\d{4})",
                    r"(\d{4})\s*[-–]\s*(?:\d{4}|present)"]:
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                val = m.group(1).strip()
                ok, cleaned, reason = validate_extraction(var_name, val)
                if ok:
                    return True, cleaned, f"Retry pattern: {reason}"

    # Strategy 2: LLM re-extraction with tighter prompt
    prompt = (f"From the following text, extract ONLY the {var_name}.\n"
              f"Reply with JUST the value, nothing else.\n\n"
              f"Text:\n{text[:1200]}")
    raw = agent.llm_query(prompt, max_tokens=40)
    val = raw.strip().strip('"').strip("'").strip(".")
    if val and len(val) < 80 and "error" not in val.lower():
        ok, cleaned, reason = validate_extraction(var_name, val)
        if ok:
            return True, cleaned, f"Retry LLM: {reason}"

    return False, original_value, "All retry strategies failed"


# ═══════════════════════════════════════════════════════════════
#  3) MEMORY INTEGRATION — Load + Substitute
# ═══════════════════════════════════════════════════════════════

def load_memory():
    """Load memory from memory_store.json. Returns dict or empty."""
    if os.path.exists(MEMORY_FILE):
        try:
            with open(MEMORY_FILE) as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    # Try memory_manager_v1
    try:
        from memory_manager_v1 import load_memory as mm_load
        return mm_load()
    except ImportError:
        pass
    return {}


def substitute_memory(text, memory, variables=None):
    """Replace {{key}} placeholders with memory or extracted variable values.

    Priority: variables (extracted) > memory (stored profile).
    """
    if not text:
        return text

    combined = dict(memory)
    if variables:
        combined.update(variables)

    for key, val in combined.items():
        text = text.replace("{{" + key + "}}", str(val))

    return text


# ═══════════════════════════════════════════════════════════════
#  V2 Fact Extraction (wrapper around v1.1 logic, with verify)
# ═══════════════════════════════════════════════════════════════

def extract_and_verify(page, extract_config, variables):
    """Extract a fact and verify it. Returns (var_name, var_val, verified, retry_used)."""
    if not extract_config:
        return None, None, False, False

    method = extract_config.get("method", "regex")
    name = extract_config.get("name", "value")
    default = extract_config.get("default", "")
    text = agent.get_text(page, 2000)

    if not text:
        return name, default, False, False

    # Primary extraction
    val = None
    if method == "regex":
        pattern = extract_config.get("pattern", "")
        if pattern:
            m = re.search(pattern, text)
            if m:
                val = (m.group(1) if m.lastindex else m.group(0)).strip()
    elif method == "llm":
        prompt_tmpl = extract_config.get("prompt", f"Extract {name} from this text.")
        prompt = (f"{prompt_tmpl}\n\nText:\n{text[:1000]}\n\n"
                  "Reply with ONLY the extracted value. Nothing else.")
        raw = agent.llm_query(prompt, max_tokens=30)
        candidate = raw.strip().strip('"').strip("'").strip(".")
        if candidate and len(candidate) < 80 and "error" not in candidate.lower():
            val = candidate

    if not val:
        val = default

    # Validate
    is_valid, cleaned, reason = validate_extraction(name, val)
    if is_valid:
        return name, cleaned, True, False

    # Single retry
    retry_ok, retry_val, retry_reason = retry_extraction(page, name, extract_config, val)
    if retry_ok:
        return name, retry_val, True, True

    # Return what we have, marked unverified
    return name, val or default, False, True


# ═══════════════════════════════════════════════════════════════
#  V2 Plan Decomposition (reuse v1.1 prompt with enhancements)
# ═══════════════════════════════════════════════════════════════

DECOMPOSE_PROMPT_V2 = """You are a task decomposition engine. Given a composite instruction, break it into sequential web subtasks.

Available domains and start URLs:
  wikipedia : https://en.wikipedia.org
  google    : https://www.google.com
  youtube   : https://www.youtube.com
  store     : http://localhost:8001/index.html
  booking   : http://localhost:8002/step1_service.html
  forum     : http://localhost:9999
  gitlab    : http://localhost:8023

Rules:
1. Each step runs on ONE domain. Steps execute sequentially.
2. Use {{variable_name}} syntax to reference extracted values from previous steps.
3. Include "extract" ONLY when a fact must carry forward to a later step.
4. Keep max_steps 5-15 per step.
5. If the user wants to WATCH/PLAY a video on YouTube, set "playback": true on that step.
6. For extraction: use "method": "llm" with a clear extraction prompt.

Output ONLY valid JSON (no markdown fences):
{
  "steps": [
    {
      "domain": "wikipedia",
      "start_url": "https://en.wikipedia.org",
      "instruction": "Search for X on Wikipedia.",
      "completion_keyword": "/wiki/X",
      "max_steps": 10,
      "extract": {
        "name": "variable_name",
        "method": "llm",
        "prompt": "Who created X?",
        "default": ""
      }
    }
  ],
  "final_completion_keyword": "..."
}

Composite instruction: """


def decompose_v2(instruction):
    """Decompose a composite instruction into executable steps."""
    raw = agent.llm_query(DECOMPOSE_PROMPT_V2 + instruction, max_tokens=800)
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

    # Fallback: YouTube playback
    if has_watch_intent(instruction) and "youtube" in instruction.lower():
        topic = re.sub(
            r'\b(watch|play|open|video|first|the|a|on|youtube|and|let|me|for|search)\b',
            '', instruction, flags=re.IGNORECASE
        ).strip() or instruction
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

    # Fallback: Google search
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
#  4) PLAN → EXECUTE → VERIFY LOOP
# ═══════════════════════════════════════════════════════════════

def run_composite_v2(ctx, scenario, run_dir, memory=None):
    """Execute a composite scenario with schema-safe results and verification.

    Args:
        ctx: Playwright browser context
        scenario: dict with name, composite_instruction, steps, final_completion_keyword
        run_dir: directory for traces/screenshots
        memory: loaded memory dict for substitution
    """
    name = scenario.get("name", "Composite V2")
    instruction = scenario.get("composite_instruction", "")
    steps = scenario.get("steps", [])
    final_kw = scenario.get("final_completion_keyword", "")
    mem = memory or {}

    print(f"\n{'━' * 72}")
    print(f"  🔗 COMPOSITE V2: {name}")
    print(f"  Instruction: {instruction[:65]}")
    print(f"  Steps: {len(steps)}  │  Final KW: {final_kw or '(none)'}")
    if mem:
        print(f"  Memory: {', '.join(f'{k}={v}' for k, v in list(mem.items())[:4])}")
    print(f"{'━' * 72}")

    variables = {}
    step_results = []
    total_agent_steps = 0
    domains = []
    retries_used = 0
    composite_ok = False
    stop_reason = "incomplete"
    final_url = ""
    playback_info = None
    keep_page_open = None

    for i, step in enumerate(steps, 1):
        step_t0 = time.time()

        # Substitute variables + memory into step fields
        step_instruction = substitute_memory(step["instruction"], mem, variables)
        step_url = substitute_memory(step["start_url"], mem, variables)
        step_kw = substitute_memory(step.get("completion_keyword", ""), mem, variables)
        step_domain = step.get("domain", "other")
        step_max = step.get("max_steps", 15)
        step_name = f"{name} → Step {i}: {step_domain}"
        step_playback = step.get("playback", False)

        if step_domain == "youtube" and not step_playback:
            step_playback = has_watch_intent(instruction) or has_watch_intent(step_instruction)

        # Header
        print(f"\n  ┌── Step {i}/{len(steps)} │ {step_domain}"
              f"{' 🎬' if step_playback else ''} ──┐")
        print(f"  │ Goal: {step_instruction[:55]}")
        if variables:
            print(f"  │ Vars: {', '.join(f'{k}={v}' for k, v in variables.items())}")

        # Execute
        page = ctx.new_page()
        retry_used = False
        step_result = StepResult(ok=False, reason="Not started")

        try:
            raw_result = agent.run_scenario(
                page, step_name, step_instruction, step_url,
                step_kw, step_max, run_dir, visual=True
            )
            step_result = normalize_result(raw_result)
            total_agent_steps += step_result.meta.get("steps_taken", 0)
            domains.append(step_domain)
            final_url = step_result.meta.get("final_url", page.url)

            # Extract + Verify if configured
            ext = step.get("extract")
            if ext and step_result.ok:
                var_name, var_val, verified, did_retry = extract_and_verify(
                    page, ext, variables
                )
                if var_name and var_val:
                    variables[var_name] = var_val
                    if did_retry:
                        retry_used = True
                        retries_used += 1
                    v_icon = "✅" if verified else "⚠️"
                    r_icon = " (retry)" if did_retry else ""
                    print(f"  📌 Extracted: {var_name} = \"{var_val}\" {v_icon}{r_icon}")
                elif var_name:
                    print(f"  ⚠ Extraction failed for '{var_name}'")

            # Playback mode
            if step_playback and step_result.ok:
                ss_dir = os.path.join(run_dir, "screenshots")
                os.makedirs(ss_dir, exist_ok=True)
                playback_info = execute_playback(page)
                total_agent_steps += 1
                try:
                    page.screenshot(path=os.path.join(ss_dir, f"playback_{i:02d}.png"))
                except Exception:
                    pass
                if playback_info.get("video_detected") or playback_info.get("url_is_watch"):
                    composite_ok = True
                    final_url = page.url
                    stop_reason = "YouTube playback started"
                    keep_page_open = page
                    print(f"\n  🎬 VIDEO READY — Browser stays open.")
                    print(f"  🎬 Title: {playback_info.get('video_title', '?')[:55]}")
                    break

            # Early stop on final keyword
            cur_url = page.url
            if final_kw and final_kw.lower() in cur_url.lower():
                composite_ok = True
                stop_reason = f"Final KW '{final_kw}' in URL at step {i}"
                print(f"  ⚡ Early stop: {stop_reason}")
                break

            if not step_result.ok:
                stop_reason = f"Step {i} failed: {step_result.reason[:50]}"
                print(f"  ⚠ {stop_reason}")
                break

        finally:
            # Step summary
            step_lat = round(time.time() - step_t0, 1)
            sr_dict = step_result.to_dict()
            sr_dict["step"] = i
            sr_dict["domain"] = step_domain
            sr_dict["instruction"] = step_instruction[:60]
            sr_dict["latency"] = step_lat
            sr_dict["retry_used"] = retry_used
            step_results.append(sr_dict)

            st = "✅" if step_result.ok else "❌"
            rt = " ↻" if retry_used else ""
            print(f"  └── {st} {step_domain} │ {step_result.reason[:40]} │ "
                  f"{step_lat}s{rt}")

            if page != keep_page_open:
                try:
                    page.close()
                except Exception:
                    pass

        if i < len(steps):
            time.sleep(1.0)

    else:
        # All steps completed
        if step_results and step_results[-1].get("ok"):
            last_url = step_results[-1].get("meta", {}).get("final_url", "")
            if final_kw and final_kw.lower() in str(last_url).lower():
                composite_ok = True
                stop_reason = f"All {len(steps)} steps done, final KW matched"
            elif not final_kw:
                composite_ok = True
                stop_reason = f"All {len(steps)} steps completed"
            else:
                composite_ok = True
                stop_reason = f"All steps passed"

    # Build summary
    result_summary = {
        "name": name,
        "composite_instruction": instruction,
        "success": composite_ok,
        "stop_reason": stop_reason,
        "steps_total": total_agent_steps,
        "domains_used": list(dict.fromkeys(domains)),
        "variables": variables,
        "retries_used": retries_used,
        "playback": playback_info,
        "final_url": final_url,
        "step_results": step_results,
    }

    st = "✅" if composite_ok else "❌"
    print(f"\n  {st} COMPOSITE V2: {name}")
    print(f"    Result: {stop_reason}")
    print(f"    Steps: {total_agent_steps}  │  Domains: {' → '.join(domains)}"
          f"  │  Retries: {retries_used}")
    if variables:
        print(f"    Variables: {variables}")

    return result_summary, keep_page_open


# ═══════════════════════════════════════════════════════════════
#  6) REPORTING
# ═══════════════════════════════════════════════════════════════

def print_detailed_report(results):
    """Print per-step and per-scenario report."""
    for r in results:
        print(f"\n  ── {r['name']} ──")
        for sr in r.get("step_results", []):
            st = "✅" if sr.get("ok") else "❌"
            rt = "yes" if sr.get("retry_used") else "no"
            val = sr.get("value")
            val_str = f'"{val}"' if val else "—"
            print(f"    Step {sr.get('step', '?')} │ {sr.get('domain', '?'):<10} │ "
                  f"{st} │ Val: {val_str:<20} │ Retry: {rt}")


def print_summary_table(results, elapsed):
    """Print final summary table."""
    print()
    print("═" * 76)
    print("  COMPOSITE V2 — FINAL SUMMARY")
    print("═" * 76)
    print(f"  {'#':>2}  {'Domain':<20}  {'Success':<8}  {'Steps':>6}  "
          f"{'Runtime':>8}  {'Retries':>8}")
    print(f"  {'─'*74}")

    total = len(results)
    ok = 0
    total_retries = 0

    for i, r in enumerate(results, 1):
        s = "✅" if r["success"] else "❌"
        if r["success"]:
            ok += 1
        doms = " → ".join(r.get("domains_used", ["?"]))
        retries = r.get("retries_used", 0)
        total_retries += retries
        steps = r.get("steps_total", 0)
        # Compute runtime from step latencies
        runtime = sum(sr.get("latency", 0) for sr in r.get("step_results", []))
        print(f"  {i:>2}  {doms:<20}  {s:<8}  {steps:>6}  "
              f"{runtime:>7.1f}s  {retries:>8}")

    print(f"  {'─'*74}")
    print(f"  Overall: {ok}/{total} ({100*ok//max(total,1)}%)  │  "
          f"Runtime: {elapsed:.1f}s  │  Retries: {total_retries}")
    print("═" * 76)


def save_report(results, run_dir, elapsed):
    """Save JSON + markdown report."""
    os.makedirs(REPORTS_DIR, exist_ok=True)

    # JSON
    json_path = os.path.join(run_dir, "composite_v2_results.json")
    with open(json_path, "w") as f:
        json.dump({
            "timestamp": datetime.now().isoformat(),
            "version": "v2",
            "elapsed": elapsed,
            "results": results,
        }, f, indent=2, default=str)

    # Markdown
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    md_path = os.path.join(REPORTS_DIR, f"report_{ts}.md")

    lines = [
        "# Composite Orchestrator V2 — Report",
        f"**Date**: {datetime.now().isoformat()}",
        f"**Runtime**: {elapsed:.1f}s",
        f"**Model**: {MODEL_NAME}",
        "",
        "## Results",
        "",
        "| # | Task | OK | Steps | Domains | Retries | Stop Reason |",
        "|---|------|----|-------|---------|---------|-------------|",
    ]
    for i, r in enumerate(results, 1):
        s = "✅" if r["success"] else "❌"
        doms = " → ".join(r.get("domains_used", []))
        lines.append(
            f"| {i} | {r['name'][:30]} | {s} | {r['steps_total']} | "
            f"{doms} | {r.get('retries_used', 0)} | "
            f"{r.get('stop_reason', '')[:35]} |"
        )

    lines += ["", "## Step Details", ""]
    for r in results:
        lines.append(f"### {r['name']}")
        lines.append("")
        for sr in r.get("step_results", []):
            st = "✅" if sr.get("ok") else "❌"
            val = sr.get("value", "")
            val_str = f'`{val}`' if val else "—"
            retry = "↻" if sr.get("retry_used") else ""
            lines.append(
                f"- Step {sr.get('step', '?')} [{sr.get('domain', '?')}]: "
                f"{st} {sr.get('reason', '')[:40]} — Val: {val_str} {retry}"
            )
        if r.get("variables"):
            lines.append(f"- **Variables**: {r['variables']}")
        lines.append("")

    with open(md_path, "w") as f:
        f.write("\n".join(lines))

    print(f"\n  📄 JSON:   {json_path}")
    print(f"  📄 Report: {md_path}")
    print(f"  📁 Run:    {run_dir}")


# ═══════════════════════════════════════════════════════════════
#  5) CLI + MAIN
# ═══════════════════════════════════════════════════════════════

def main():
    ap = argparse.ArgumentParser(description="Composite Orchestrator V2")
    ap.add_argument("--scenarios", type=str, default=None,
                    help="JSON file with composite scenarios")
    ap.add_argument("--instruction", type=str, default=None,
                    help="Single composite instruction")
    ap.add_argument("--headless", type=str, default="false")
    ap.add_argument("--visual", action="store_true", default=True)
    args = ap.parse_args()

    headless = args.headless.lower() in ("true", "1", "yes")

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("❌ playwright not installed")
        sys.exit(1)

    # Load memory
    memory = load_memory()

    # Load scenarios
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
    run_dir = os.path.join(SCRIPT_DIR, "runs", f"v2_{ts}")
    os.makedirs(run_dir, exist_ok=True)

    print()
    print("══════════════════════════════════════════════════════════")
    print("  COMPOSITE ORCHESTRATOR V2")
    print("══════════════════════════════════════════════════════════")
    print(f"  Model:     {MODEL_NAME}")
    print(f"  Memory:    {len(memory)} keys loaded")
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
                    r, kp = run_composite_v2(ctx, sc, run_dir, memory=memory)
                    results.append(r)
                    if kp:
                        keep_alive_page = kp
                    if i < len(scenarios):
                        time.sleep(1.5)

            elif args.instruction:
                instr = args.instruction
                print(f"\n  🧠 Decomposing: \"{instr[:60]}\"...")
                plan = decompose_v2(instr)
                print(f"  Plan: {len(plan.get('steps', []))} steps")
                for j, s in enumerate(plan.get("steps", []), 1):
                    pb = " 🎬" if s.get("playback") else ""
                    ext = " 📌" if s.get("extract") else ""
                    print(f"    {j}. [{s.get('domain')}] "
                          f"{s.get('instruction', '?')[:45]}{pb}{ext}")

                sc = {
                    "name": "CLI Instruction",
                    "composite_instruction": instr,
                    "final_completion_keyword": plan.get("final_completion_keyword", ""),
                    "steps": plan["steps"],
                }
                r, kp = run_composite_v2(ctx, sc, run_dir, memory=memory)
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
                        print("\n  Bye!")
                        break
                    if not instr or instr.lower() in ("quit", "exit", "q"):
                        break
                    idx += 1
                    print(f"\n  🧠 Decomposing instruction...")
                    plan = decompose_v2(instr)
                    print(f"  Plan: {len(plan.get('steps', []))} steps")
                    for j, s in enumerate(plan.get("steps", []), 1):
                        pb = " 🎬" if s.get("playback") else ""
                        ext = " 📌" if s.get("extract") else ""
                        print(f"    {j}. [{s.get('domain')}] "
                              f"{s.get('instruction', '?')[:45]}{pb}{ext}")

                    sc = {
                        "name": f"Interactive-{idx}",
                        "composite_instruction": instr,
                        "final_completion_keyword": plan.get("final_completion_keyword", ""),
                        "steps": plan["steps"],
                    }
                    r, kp = run_composite_v2(ctx, sc, run_dir, memory=memory)
                    results.append(r)
                    if kp:
                        keep_alive_page = kp
                        print("\n  🎬 Browser is open. Video is playing.")
                        try:
                            input("  Press Enter when done watching... ")
                        except (EOFError, KeyboardInterrupt):
                            print()
                        break

            # Wait for playback if needed
            if keep_alive_page and args.instruction:
                print("\n  🎬 Browser is open. Video is playing.")
                print("  Press Enter when done watching...")
                try:
                    input()
                except (EOFError, KeyboardInterrupt):
                    print()

        finally:
            try:
                ctx.close()
                browser.close()
            except Exception:
                pass

    elapsed = round(time.time() - t0, 1)

    if not results:
        print("\n  No results.")
        return

    # Structured output
    print_detailed_report(results)
    print_summary_table(results, elapsed)
    save_report(results, run_dir, elapsed)

    print()
    print("══════════════════════════════════════════════════════════")
    print("  COMPOSITE V2 READY.")
    print("══════════════════════════════════════════════════════════")


if __name__ == "__main__":
    main()
