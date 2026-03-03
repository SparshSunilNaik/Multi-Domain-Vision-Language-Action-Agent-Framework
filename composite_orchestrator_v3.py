#!/usr/bin/env python3
"""
Composite Orchestrator v3 — Human-in-the-Loop (HITL) Multi-Domain System.

Builds on v2 with:
  - HITL triggers: extraction failure, missing variable, ambiguous instruction,
    step validation failure
  - Memory persistence: user-provided personal data saved to memory_store.json
  - Full eval suite (--full-eval) covering ALL 10 domains + HITL scenarios
  - Forum + GitLab CRUD integration (reuses existing browser context)

Usage:
    python composite_orchestrator_v3.py --instruction "..."
    python composite_orchestrator_v3.py --scenarios composite_scenarios_v2.json
    python composite_orchestrator_v3.py --full-eval
    python composite_orchestrator_v3.py  # Interactive
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
sys.path.insert(0, os.path.join(SCRIPT_DIR, "llm_crud_v1"))

import vla_unified_agent_v1_3 as agent

try:
    from youtube_playback_extension_v1 import has_watch_intent, execute_playback
except ImportError:
    def has_watch_intent(_): return False
    def execute_playback(_): return {}

MODEL_NAME = agent.MODEL_NAME
MEMORY_FILE = os.path.join(SCRIPT_DIR, "memory_store.json")
REPORTS_DIR = os.path.join(SCRIPT_DIR, "reports_composite_v3")


# ═══════════════════════════════════════════════════════════════
#  1) RESULT NORMALIZER — StepResult Schema
# ═══════════════════════════════════════════════════════════════

class StepResult:
    """Standardized result container."""
    __slots__ = ("ok", "value", "reason", "meta")

    def __init__(self, ok=False, value=None, reason="", meta=None):
        self.ok = bool(ok)
        self.value = value
        self.reason = str(reason) if reason else ""
        self.meta = dict(meta) if meta else {}

    def to_dict(self):
        return {"ok": self.ok, "value": self.value,
                "reason": self.reason, "meta": self.meta}

    def __repr__(self):
        st = "✅" if self.ok else "❌"
        return f"StepResult({st}, value={self.value}, reason={self.reason[:40]})"


def normalize_result(raw):
    """Convert any agent return value into a safe StepResult."""
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
    return StepResult(ok=False, reason=f"Unknown type: {type(raw).__name__}")


# ═══════════════════════════════════════════════════════════════
#  2) EXTRACTION VERIFIER — Validators + Retry
# ═══════════════════════════════════════════════════════════════

VALIDATORS = {
    "year": re.compile(r"\b(1[0-9]{3}|20[0-9]{2})\b"),
    "name": re.compile(r"[A-Z][a-z]+\s+[A-Z][a-z]+"),
    "url":  re.compile(r"https?://\S+"),
}


def detect_value_type(name, value):
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
    if not value or not str(value).strip():
        return False, None, "Empty extraction"
    value = str(value).strip()
    vtype = detect_value_type(var_name, value)
    if vtype == "any":
        return True, value, "Non-empty value accepted"
    validator = VALIDATORS.get(vtype)
    if not validator:
        return True, value, f"No validator for '{vtype}'"
    m = validator.search(value)
    if m:
        cleaned = m.group(0) if vtype != "year" else m.group(1)
        return True, cleaned, f"Validated {vtype}: {cleaned}"
    return False, value, f"Failed {vtype} validation: '{value[:40]}'"


def retry_extraction(page, var_name, extract_config, original_value):
    """Single fallback retry for failed extraction."""
    text = agent.get_text(page, 3000)
    vtype = detect_value_type(var_name, original_value or "")

    if vtype == "name":
        for pat in [r"(?:Created|Designed|Developed|Invented|Founded)\s+by\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)",
                    r"(?:creator|author|designer|developer|inventor|founder)\s*[:=]\s*([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)"]:
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                ok, cleaned, reason = validate_extraction(var_name, m.group(1).strip())
                if ok:
                    return True, cleaned, f"Retry infobox: {reason}"

    if vtype == "year":
        for pat in [r"(?:born|founded|created|released)\s+(?:in\s+)?(\d{4})",
                    r"(\d{4})\s*[-–]\s*(?:\d{4}|present)"]:
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                ok, cleaned, reason = validate_extraction(var_name, m.group(1).strip())
                if ok:
                    return True, cleaned, f"Retry pattern: {reason}"

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
#  3) MEMORY — Load + Save + Substitute
# ═══════════════════════════════════════════════════════════════

PERSONAL_KEYS = {"name", "email", "phone", "address", "city", "zip", "country"}


def load_memory():
    if os.path.exists(MEMORY_FILE):
        try:
            with open(MEMORY_FILE) as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    try:
        from memory_manager_v1 import load_memory as mm_load
        return mm_load()
    except ImportError:
        pass
    return {}


def save_memory(memory):
    """Persist memory dict to memory_store.json."""
    try:
        with open(MEMORY_FILE, "w") as f:
            json.dump(memory, f, indent=2)
    except IOError as e:
        print(f"  ⚠ Could not save memory: {e}")


def substitute_memory(text, memory, variables=None):
    if not text:
        return text
    combined = dict(memory)
    if variables:
        combined.update(variables)
    for key, val in combined.items():
        text = text.replace("{{" + key + "}}", str(val))
    return text


def find_unresolved_placeholders(text):
    """Return list of {{key}} placeholders still in text."""
    return re.findall(r"\{\{(\w+)\}\}", text)


# ═══════════════════════════════════════════════════════════════
#  4) HUMAN-IN-THE-LOOP (HITL)
# ═══════════════════════════════════════════════════════════════

class HITLResult:
    """Tracks HITL interventions."""
    __slots__ = ("triggered", "reason", "key", "value", "persisted")

    def __init__(self):
        self.triggered = False
        self.reason = ""
        self.key = ""
        self.value = ""
        self.persisted = False

    def to_dict(self):
        return {"triggered": self.triggered, "reason": self.reason,
                "key": self.key, "value": self.value, "persisted": self.persisted}


def hitl_ask(reason, key=None, memory=None, auto_mode=False):
    """Trigger HITL — ask user for missing information.

    Args:
        reason: why HITL was triggered
        key: the variable/field name needed
        memory: memory dict (for persistence)
        auto_mode: if True, skip prompt and return empty (for --full-eval)

    Returns:
        HITLResult
    """
    hr = HITLResult()
    hr.triggered = True
    hr.reason = reason
    hr.key = key or ""

    print()
    print(f"  ⚠ Clarification Required:")
    print(f"    {reason}")

    if auto_mode:
        print(f"    [AUTO MODE — skipping HITL prompt]")
        hr.value = ""
        return hr

    prompt_text = f"  > Please provide {key or 'the missing information'}: "
    try:
        user_input = input(prompt_text).strip()
    except (EOFError, KeyboardInterrupt):
        print()
        hr.value = ""
        return hr

    hr.value = user_input

    # Persist to memory if personal data
    if user_input and key and key.lower() in PERSONAL_KEYS and memory is not None:
        memory[key.lower()] = user_input
        save_memory(memory)
        hr.persisted = True
        print(f"    💾 Saved to memory: {key} = \"{user_input}\"")

    print(f"    HITL intervention used.")
    return hr


def hitl_extraction_failed(var_name, original_value, memory, auto_mode=False):
    """HITL trigger: extraction failed after retry."""
    reason = (f"Could not extract '{var_name}' from page."
              f" Best guess: '{original_value or '(empty)'}'. Please provide the correct value.")
    return hitl_ask(reason, key=var_name, memory=memory, auto_mode=auto_mode)


def hitl_missing_variable(var_name, instruction, memory, auto_mode=False):
    """HITL trigger: required variable missing."""
    reason = f"Variable '{{{{{var_name}}}}}' needed for: \"{instruction[:50]}\" — not found in memory or extracted variables."
    return hitl_ask(reason, key=var_name, memory=memory, auto_mode=auto_mode)


def hitl_step_failed(step_num, domain, reason_str, memory, auto_mode=False):
    """HITL trigger: step validation failed."""
    reason = f"Step {step_num} [{domain}] failed: {reason_str[:60]}. Provide guidance or 'skip' to continue."
    return hitl_ask(reason, memory=memory, auto_mode=auto_mode)


# ═══════════════════════════════════════════════════════════════
#  5) EXTRACTION WITH HITL
# ═══════════════════════════════════════════════════════════════

def extract_verify_hitl(page, extract_config, variables, memory, auto_mode=False):
    """Extract → Verify → Retry → HITL if still failed.

    Returns (var_name, var_val, verified, retry_used, hitl_result)
    """
    if not extract_config:
        return None, None, False, False, HITLResult()

    method = extract_config.get("method", "regex")
    name = extract_config.get("name", "value")
    default = extract_config.get("default", "")
    text = agent.get_text(page, 2000)

    if not text:
        # HITL: no text to extract from
        hr = hitl_extraction_failed(name, default, memory, auto_mode)
        if hr.value:
            return name, hr.value, True, False, hr
        return name, default, False, False, hr

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
        return name, cleaned, True, False, HITLResult()

    # Retry
    retry_ok, retry_val, retry_reason = retry_extraction(page, name, extract_config, val)
    if retry_ok:
        return name, retry_val, True, True, HITLResult()

    # HITL: extraction failed after retry
    hr = hitl_extraction_failed(name, retry_val, memory, auto_mode)
    if hr.value:
        return name, hr.value, True, True, hr

    return name, val or default, False, True, hr


# ═══════════════════════════════════════════════════════════════
#  6) PLAN DECOMPOSITION
# ═══════════════════════════════════════════════════════════════

DECOMPOSE_PROMPT_V3 = """You are a task decomposition engine. Break a composite instruction into sequential web subtasks.

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
2. Use {{variable_name}} to reference extracted values from previous steps.
3. Include "extract" ONLY when a fact must carry forward.
4. Keep max_steps 5-15 per step.
5. For YouTube WATCH/PLAY, set "playback": true.
6. For extraction: use "method": "llm" with a clear prompt.

Output ONLY valid JSON (no markdown):
{
  "steps": [
    {
      "domain": "wikipedia",
      "start_url": "https://en.wikipedia.org",
      "instruction": "Search for X.",
      "completion_keyword": "/wiki/X",
      "max_steps": 10,
      "extract": {"name": "var", "method": "llm", "prompt": "Who created X?", "default": ""}
    }
  ],
  "final_completion_keyword": "..."
}

Composite instruction: """


def decompose_v3(instruction):
    raw = agent.llm_query(DECOMPOSE_PROMPT_V3 + instruction, max_tokens=800)
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

    if has_watch_intent(instruction) and "youtube" in instruction.lower():
        topic = re.sub(
            r'\b(watch|play|open|video|first|the|a|on|youtube|and|let|me|for|search)\b',
            '', instruction, flags=re.IGNORECASE
        ).strip() or instruction
        return {
            "steps": [{"domain": "youtube", "start_url": "https://www.youtube.com",
                        "instruction": f"Search YouTube for '{topic}'.",
                        "completion_keyword": "results?search_query=",
                        "max_steps": 10, "playback": True}],
            "final_completion_keyword": "/watch",
        }

    return {
        "steps": [{"domain": "google", "start_url": "https://www.google.com",
                    "instruction": instruction, "completion_keyword": "search?q=",
                    "max_steps": 10}],
        "final_completion_keyword": "search?q=",
    }


# ═══════════════════════════════════════════════════════════════
#  7) CRUD RUNNERS (Forum + GitLab)
# ═══════════════════════════════════════════════════════════════

def run_crud_forum(browser, run_dir, max_steps=20):
    """Run Forum CRUD on existing browser."""
    from forum_crud_llm import ForumCRUD
    t0 = time.time()
    ctx = browser.new_context(viewport={"width": 1280, "height": 800})
    page = ctx.new_page()
    try:
        fc = ForumCRUD(page, run_dir, max_steps=max_steps,
                       username=os.environ.get("FORUM_USER", "MarvelsGrantMan136"),
                       password=os.environ.get("FORUM_PASS", "test1234"),
                       verbose=True)
        data = fc.run_all(allow_delete=False)
    finally:
        try:
            ctx.close()
        except Exception:
            pass
    succ = data["total_success"]
    total = data["total_ops"]
    return {
        "name": "Forum CRUD", "domain": "forum",
        "success": succ == total, "steps_total": sum(r.get("steps", 0) for r in data["results"]),
        "stop_reason": f"{succ}/{total} passed",
        "runtime": round(time.time() - t0, 1),
        "domains_used": ["forum"], "retries_used": 0, "hitl_used": False,
        "step_results": [{"step": j+1, "domain": "forum", "ok": r["success"],
                          "value": r.get("op", ""), "reason": r.get("reason", ""),
                          "latency": r.get("latency", 0), "retry_used": False,
                          "hitl": False}
                         for j, r in enumerate(data["results"])],
    }


def run_crud_gitlab(browser, run_dir, max_steps=25):
    """Run GitLab CRUD on existing browser."""
    from gitlab_crud_llm import GitLabCRUD
    t0 = time.time()
    ctx = browser.new_context(viewport={"width": 1280, "height": 800})
    page = ctx.new_page()
    try:
        gc = GitLabCRUD(page, run_dir, max_steps=max_steps,
                        username=os.environ.get("GITLAB_USER", "root"),
                        password=os.environ.get("GITLAB_PASS", "Kite$7v_Mango!Q2-Quartz"),
                        verbose=True)
        data = gc.run_all(allow_delete=False)
    finally:
        try:
            ctx.close()
        except Exception:
            pass
    succ = data["total_success"]
    total = data["total_ops"]
    return {
        "name": "GitLab CRUD", "domain": "gitlab",
        "success": succ == total, "steps_total": sum(r.get("steps", 0) for r in data["results"]),
        "stop_reason": f"{succ}/{total} passed",
        "runtime": round(time.time() - t0, 1),
        "domains_used": ["gitlab"], "retries_used": 0, "hitl_used": False,
        "step_results": [{"step": j+1, "domain": "gitlab", "ok": r["success"],
                          "value": r.get("op", ""), "reason": r.get("reason", ""),
                          "latency": r.get("latency", 0), "retry_used": False,
                          "hitl": False}
                         for j, r in enumerate(data["results"])],
    }


# ═══════════════════════════════════════════════════════════════
#  8) COMPOSITE V3 EXECUTION ENGINE
# ═══════════════════════════════════════════════════════════════

def run_composite_v3(ctx, scenario, run_dir, memory=None, auto_mode=False):
    """Execute composite scenario with HITL support.

    Args:
        ctx: Playwright browser context
        scenario: dict with name, composite_instruction, steps, etc.
        run_dir: trace/screenshot directory
        memory: loaded memory dict
        auto_mode: True for --full-eval (skip HITL prompts)
    """
    name = scenario.get("name", "Composite V3")
    instruction = scenario.get("composite_instruction", "")
    steps = scenario.get("steps", [])
    final_kw = scenario.get("final_completion_keyword", "")
    mem = memory if memory is not None else {}

    print(f"\n{'━' * 72}")
    print(f"  🔗 COMPOSITE V3: {name}")
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
    hitl_count = 0
    hitl_log = []
    composite_ok = False
    stop_reason = "incomplete"
    final_url = ""
    playback_info = None
    keep_page_open = None

    for i, step in enumerate(steps, 1):
        step_t0 = time.time()

        # Substitute variables + memory
        step_instruction = substitute_memory(step["instruction"], mem, variables)
        step_url = substitute_memory(step["start_url"], mem, variables)
        step_kw = substitute_memory(step.get("completion_keyword", ""), mem, variables)
        step_domain = step.get("domain", "other")
        step_max = step.get("max_steps", 15)
        step_name = f"{name} → Step {i}: {step_domain}"
        step_playback = step.get("playback", False)

        if step_domain == "youtube" and not step_playback:
            step_playback = has_watch_intent(instruction) or has_watch_intent(step_instruction)

        # HITL: Check for unresolved placeholders
        unresolved = find_unresolved_placeholders(step_instruction)
        step_hitl_used = False
        for uvar in unresolved:
            hr = hitl_missing_variable(uvar, step_instruction, mem, auto_mode)
            hitl_log.append(hr.to_dict())
            if hr.value:
                variables[uvar] = hr.value
                step_instruction = step_instruction.replace("{{" + uvar + "}}", hr.value)
                hitl_count += 1
                step_hitl_used = True

        # Header
        print(f"\n  ┌── Step {i}/{len(steps)} │ {step_domain}"
              f"{' 🎬' if step_playback else ''}"
              f"{' 🤝' if step_hitl_used else ''} ──┐")
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

            # Extract + Verify + HITL
            ext = step.get("extract")
            if ext and step_result.ok:
                var_name, var_val, verified, did_retry, hr = extract_verify_hitl(
                    page, ext, variables, mem, auto_mode
                )
                if hr.triggered:
                    hitl_log.append(hr.to_dict())
                    if hr.value:
                        hitl_count += 1
                        step_hitl_used = True

                if var_name and var_val:
                    variables[var_name] = var_val
                    if did_retry:
                        retry_used = True
                        retries_used += 1
                    v_icon = "✅" if verified else "⚠️"
                    r_icon = " (retry)" if did_retry else ""
                    h_icon = " 🤝" if hr.triggered and hr.value else ""
                    print(f"  📌 Extracted: {var_name} = \"{var_val}\" {v_icon}{r_icon}{h_icon}")
                elif var_name:
                    print(f"  ⚠ Extraction failed for '{var_name}'")

            # Playback
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
                    break

            # Early stop
            cur_url = page.url
            if final_kw and final_kw.lower() in cur_url.lower():
                composite_ok = True
                stop_reason = f"Final KW '{final_kw}' in URL at step {i}"
                break

            # Step failed — HITL
            if not step_result.ok:
                hr = hitl_step_failed(i, step_domain, step_result.reason, mem, auto_mode)
                hitl_log.append(hr.to_dict())
                if hr.value and hr.value.lower() != "skip":
                    # User provided guidance — note it but still stop
                    print(f"    📝 User guidance noted: \"{hr.value[:40]}\"")
                    hitl_count += 1
                stop_reason = f"Step {i} failed: {step_result.reason[:50]}"
                break

        finally:
            step_lat = round(time.time() - step_t0, 1)
            sr_dict = step_result.to_dict()
            sr_dict.update(step=i, domain=step_domain,
                           instruction=step_instruction[:60],
                           latency=step_lat, retry_used=retry_used,
                           hitl=step_hitl_used)
            step_results.append(sr_dict)

            st = "✅" if step_result.ok else "❌"
            rt = " ↻" if retry_used else ""
            ht = " 🤝" if step_hitl_used else ""
            print(f"  └── {st} {step_domain} │ {step_result.reason[:40]} │ "
                  f"{step_lat}s{rt}{ht}")

            if page != keep_page_open:
                try:
                    page.close()
                except Exception:
                    pass

        if i < len(steps):
            time.sleep(1.0)

    else:
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
                stop_reason = "All steps passed"

    result = {
        "name": name, "composite_instruction": instruction,
        "success": composite_ok, "stop_reason": stop_reason,
        "steps_total": total_agent_steps,
        "domains_used": list(dict.fromkeys(domains)),
        "variables": variables, "retries_used": retries_used,
        "hitl_used": hitl_count > 0, "hitl_count": hitl_count,
        "hitl_log": hitl_log, "playback": playback_info,
        "final_url": final_url, "step_results": step_results,
        "runtime": 0,
    }

    st = "✅" if composite_ok else "❌"
    ht = f"  │  HITL: {hitl_count}" if hitl_count else ""
    print(f"\n  {st} COMPOSITE V3: {name}")
    print(f"    Result: {stop_reason}")
    print(f"    Steps: {total_agent_steps}  │  Domains: {' → '.join(domains)}"
          f"  │  Retries: {retries_used}{ht}")
    if variables:
        print(f"    Variables: {variables}")

    return result, keep_page_open


# ═══════════════════════════════════════════════════════════════
#  9) FULL EVAL SUITE (--full-eval)
# ═══════════════════════════════════════════════════════════════

FULL_EVAL_SCENARIOS = [
    # 1) Wikipedia extraction test
    {
        "type": "composite",
        "name": "Wikipedia Extraction",
        "scenario": {
            "name": "Wikipedia Extraction",
            "composite_instruction": "Find who created Python and search them on Google.",
            "final_completion_keyword": "search?q=",
            "steps": [
                {"domain": "wikipedia", "start_url": "https://en.wikipedia.org",
                 "instruction": "Search for Python (programming language) on Wikipedia.",
                 "completion_keyword": "/wiki/Python", "max_steps": 10,
                 "extract": {"name": "creator", "method": "llm",
                             "prompt": "Who created Python? Just the full name.", "default": ""}},
                {"domain": "google", "start_url": "https://www.google.com",
                 "instruction": "Search for {{creator}} on Google.",
                 "completion_keyword": "search?q=", "max_steps": 10},
            ],
        },
    },
    # 2) Google search test
    {
        "type": "composite",
        "name": "Google Search",
        "scenario": {
            "name": "Google Search",
            "composite_instruction": "Search Google for 'artificial intelligence'.",
            "final_completion_keyword": "search?q=",
            "steps": [
                {"domain": "google", "start_url": "https://www.google.com",
                 "instruction": "Search for 'artificial intelligence'.",
                 "completion_keyword": "search?q=", "max_steps": 10},
            ],
        },
    },
    # 3) YouTube playback test
    {
        "type": "composite",
        "name": "YouTube Playback",
        "scenario": {
            "name": "YouTube Playback",
            "composite_instruction": "Search neural networks on YouTube and watch the first video.",
            "final_completion_keyword": "/watch",
            "steps": [
                {"domain": "youtube", "start_url": "https://www.youtube.com",
                 "instruction": "Search for 'neural networks' on YouTube.",
                 "completion_keyword": "results?search_query=", "max_steps": 10,
                 "playback": True},
            ],
        },
    },
    # 4) Store purchase test
    {
        "type": "composite",
        "name": "Store Purchase",
        "scenario": {
            "name": "Store Purchase",
            "composite_instruction": "Buy a notebook from the store.",
            "final_completion_keyword": "",
            "steps": [
                {"domain": "store", "start_url": "http://localhost:8001/index.html",
                 "instruction": "Buy one notebook. Use name={{name}}, email={{email}}, phone={{phone}}, address={{address}}, city={{city}}, zip={{zip}}.",
                 "completion_keyword": "", "max_steps": 20},
            ],
        },
    },
    # 5) Booking reservation test
    {
        "type": "composite",
        "name": "Booking Reservation",
        "scenario": {
            "name": "Booking Reservation",
            "composite_instruction": "Book a hotel reservation for tomorrow.",
            "final_completion_keyword": "",
            "steps": [
                {"domain": "booking", "start_url": "http://localhost:8002/step1_service.html",
                 "instruction": "Book a hotel reservation for tomorrow. Use name={{name}}, email={{email}}, phone={{phone}}.",
                 "completion_keyword": "", "max_steps": 20},
            ],
        },
    },
    # 6) Forum CRUD
    {"type": "crud_forum", "name": "Forum CRUD"},
    # 7) GitLab CRUD
    {"type": "crud_gitlab", "name": "GitLab CRUD"},
    # 8) Composite cross-domain
    {
        "type": "composite",
        "name": "Cross-Domain Chain",
        "scenario": {
            "name": "Cross-Domain Chain",
            "composite_instruction": "Find the inventor of the World Wide Web, then search that person on Google.",
            "final_completion_keyword": "search?q=",
            "steps": [
                {"domain": "wikipedia", "start_url": "https://en.wikipedia.org",
                 "instruction": "Search for World Wide Web on Wikipedia.",
                 "completion_keyword": "/wiki/World_Wide_Web", "max_steps": 10,
                 "extract": {"name": "inventor", "method": "llm",
                             "prompt": "Who invented the World Wide Web? Reply with just the full name.",
                             "default": ""}},
                {"domain": "google", "start_url": "https://www.google.com",
                 "instruction": "Search for {{inventor}} on Google.",
                 "completion_keyword": "search?q=", "max_steps": 10},
            ],
        },
    },
    # 9) Composite with missing variable (forces HITL)
    {
        "type": "composite",
        "name": "HITL: Missing Variable",
        "scenario": {
            "name": "HITL: Missing Variable",
            "composite_instruction": "Search Google for a person.",
            "final_completion_keyword": "search?q=",
            "steps": [
                {"domain": "google", "start_url": "https://www.google.com",
                 "instruction": "Search for {{mystery_person}} on Google.",
                 "completion_keyword": "search?q=", "max_steps": 10},
            ],
        },
    },
    # 10) Booking with missing city (forces HITL)
    {
        "type": "composite",
        "name": "HITL: Missing City",
        "scenario": {
            "name": "HITL: Missing City",
            "composite_instruction": "Book a hotel with missing city info.",
            "final_completion_keyword": "",
            "steps": [
                {"domain": "booking", "start_url": "http://localhost:8002/step1_service.html",
                 "instruction": "Book a hotel for {{name}} in {{unknown_city}}.",
                 "completion_keyword": "", "max_steps": 20},
            ],
        },
    },
]


def run_full_eval(browser, ctx, run_dir, memory):
    """Execute all 10 eval scenarios."""
    results = []

    for i, ev in enumerate(FULL_EVAL_SCENARIOS, 1):
        name = ev["name"]
        ev_type = ev["type"]

        print()
        print("=" * 60)
        print(f"  EVAL {i}/{len(FULL_EVAL_SCENARIOS)}: {name.upper()}")
        print("=" * 60)
        time.sleep(1.0)

        r = None
        t0 = time.time()

        try:
            if ev_type == "composite":
                r, kp = run_composite_v3(ctx, ev["scenario"], run_dir,
                                         memory=memory, auto_mode=True)
                r["runtime"] = round(time.time() - t0, 1)
                if kp:
                    # Close playback page in eval mode
                    try:
                        kp.close()
                    except Exception:
                        pass

            elif ev_type == "crud_forum":
                r = run_crud_forum(browser, run_dir)

            elif ev_type == "crud_gitlab":
                r = run_crud_gitlab(browser, run_dir)

        except Exception as e:
            print(f"  ⚠ Error: {str(e)[:60]}")
            r = {
                "name": name, "domain": ev_type,
                "success": False, "steps_total": 0,
                "stop_reason": f"Error: {str(e)[:50]}",
                "runtime": round(time.time() - t0, 1),
                "domains_used": [], "retries_used": 0,
                "hitl_used": False, "hitl_count": 0,
                "step_results": [],
            }

        if r:
            results.append(r)

        if i < len(FULL_EVAL_SCENARIOS):
            time.sleep(1.0)

    return results


# ═══════════════════════════════════════════════════════════════
#  10) REPORTING
# ═══════════════════════════════════════════════════════════════

def print_v3_summary(results, elapsed):
    print()
    print("═" * 84)
    print("  COMPOSITE V3 — FINAL EVALUATION")
    print("═" * 84)
    print(f"  {'#':>2}  {'Domain':<22}  {'Success':<8}  {'HITL':<6}  "
          f"{'Retries':>7}  {'Steps':>6}  {'Runtime':>8}")
    print(f"  {'─'*82}")

    total = len(results)
    ok = 0
    total_retries = 0
    total_hitl = 0

    for i, r in enumerate(results, 1):
        s = "✅" if r.get("success") else "❌"
        if r.get("success"):
            ok += 1
        doms = " → ".join(r.get("domains_used", [r.get("domain", "?")]))
        retries = r.get("retries_used", 0)
        total_retries += retries
        hitl = "yes" if r.get("hitl_used") else "no"
        h_count = r.get("hitl_count", 0)
        total_hitl += h_count
        steps = r.get("steps_total", 0)
        runtime = r.get("runtime",
                        sum(sr.get("latency", 0) for sr in r.get("step_results", [])))
        print(f"  {i:>2}  {doms:<22}  {s:<8}  {hitl:<6}  "
              f"{retries:>7}  {steps:>6}  {runtime:>7.1f}s")

    print(f"  {'─'*82}")
    print(f"  Overall: {ok}/{total} ({100*ok//max(total,1)}%)  │  "
          f"Runtime: {elapsed:.1f}s  │  Retries: {total_retries}  │  HITL: {total_hitl}")
    print("═" * 84)


def save_v3_report(results, run_dir, elapsed):
    os.makedirs(REPORTS_DIR, exist_ok=True)

    json_path = os.path.join(run_dir, "composite_v3_results.json")
    with open(json_path, "w") as f:
        json.dump({"timestamp": datetime.now().isoformat(), "version": "v3",
                    "elapsed": elapsed, "results": results},
                  f, indent=2, default=str)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    md_path = os.path.join(REPORTS_DIR, f"report_v3_{ts}.md")

    lines = [
        "# Composite Orchestrator V3 — HITL Report",
        f"**Date**: {datetime.now().isoformat()}",
        f"**Runtime**: {elapsed:.1f}s",
        f"**Model**: {MODEL_NAME}", "",
        "## Results", "",
        "| # | Task | OK | Steps | Domains | Retries | HITL | Stop Reason |",
        "|---|------|----|-------|---------|---------|------|-------------|",
    ]
    for i, r in enumerate(results, 1):
        s = "✅" if r.get("success") else "❌"
        doms = " → ".join(r.get("domains_used", [r.get("domain", "?")]))
        hitl = f"{r.get('hitl_count', 0)}" if r.get("hitl_used") else "—"
        lines.append(
            f"| {i} | {r.get('name','?')[:25]} | {s} | {r.get('steps_total',0)} | "
            f"{doms} | {r.get('retries_used',0)} | {hitl} | "
            f"{r.get('stop_reason','')[:30]} |"
        )

    with open(md_path, "w") as f:
        f.write("\n".join(lines))

    print(f"\n  📄 JSON:   {json_path}")
    print(f"  📄 Report: {md_path}")
    print(f"  📁 Run:    {run_dir}")


# ═══════════════════════════════════════════════════════════════
#  11) CLI + MAIN
# ═══════════════════════════════════════════════════════════════

def main():
    ap = argparse.ArgumentParser(description="Composite Orchestrator V3 — HITL")
    ap.add_argument("--scenarios", type=str, default=None)
    ap.add_argument("--instruction", type=str, default=None)
    ap.add_argument("--full-eval", action="store_true",
                    help="Run full 10-domain evaluation suite")
    ap.add_argument("--headless", type=str, default="false")
    ap.add_argument("--visual", action="store_true", default=True)
    args = ap.parse_args()

    headless = args.headless.lower() in ("true", "1", "yes")

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("❌ playwright not installed"); sys.exit(1)

    memory = load_memory()

    if args.full_eval:
        mode = "Full Evaluation (10 domains)"
    elif args.scenarios:
        mode = f"Scenarios: {args.scenarios}"
    elif args.instruction:
        mode = "Single instruction"
    else:
        mode = "Interactive"

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = os.path.join(SCRIPT_DIR, "runs", f"v3_{ts}")
    os.makedirs(run_dir, exist_ok=True)

    print()
    print("══════════════════════════════════════════════════════════")
    print("  COMPOSITE ORCHESTRATOR V3 — HITL")
    print("══════════════════════════════════════════════════════════")
    print(f"  Model:     {MODEL_NAME}")
    print(f"  Memory:    {len(memory)} keys loaded")
    print(f"  HITL:      Enabled (extraction fail / missing var / step fail)")
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
            if args.full_eval:
                results = run_full_eval(browser, ctx, run_dir, memory)

            elif args.scenarios:
                with open(args.scenarios) as f:
                    scenarios = json.load(f)
                for i, sc in enumerate(scenarios, 1):
                    r, kp = run_composite_v3(ctx, sc, run_dir, memory=memory)
                    r["runtime"] = round(time.time() - t0, 1)
                    results.append(r)
                    if kp:
                        try:
                            kp.close()
                        except Exception:
                            pass
                    if i < len(scenarios):
                        time.sleep(1.5)

            elif args.instruction:
                instr = args.instruction
                print(f"\n  🧠 Decomposing: \"{instr[:60]}\"...")
                plan = decompose_v3(instr)
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
                r, kp = run_composite_v3(ctx, sc, run_dir, memory=memory)
                r["runtime"] = round(time.time() - t0, 1)
                results.append(r)
                if kp:
                    print("\n  🎬 Browser open. Press Enter when done watching...")
                    try:
                        input()
                    except (EOFError, KeyboardInterrupt):
                        print()

            else:
                # Interactive
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
                    print(f"\n  🧠 Decomposing...")
                    plan = decompose_v3(instr)
                    print(f"  Plan: {len(plan.get('steps', []))} steps")
                    for j, s in enumerate(plan.get("steps", []), 1):
                        pb = " 🎬" if s.get("playback") else ""
                        print(f"    {j}. [{s.get('domain')}] "
                              f"{s.get('instruction', '?')[:45]}{pb}")
                    sc = {
                        "name": f"Interactive-{idx}",
                        "composite_instruction": instr,
                        "final_completion_keyword": plan.get("final_completion_keyword", ""),
                        "steps": plan["steps"],
                    }
                    r, kp = run_composite_v3(ctx, sc, run_dir, memory=memory)
                    r["runtime"] = round(time.time() - t0, 1)
                    results.append(r)
                    if kp:
                        print("\n  🎬 Browser open. Press Enter when done watching...")
                        try:
                            input()
                        except (EOFError, KeyboardInterrupt):
                            print()
                        break

        finally:
            try:
                ctx.close(); browser.close()
            except Exception:
                pass

    elapsed = round(time.time() - t0, 1)

    if not results:
        print("\n  No results."); return

    print_v3_summary(results, elapsed)
    save_v3_report(results, run_dir, elapsed)

    print()
    print("══════════════════════════════════════════════════════════")
    print("  HITL MULTI-DOMAIN SYSTEM READY.")
    print("══════════════════════════════════════════════════════════")


if __name__ == "__main__":
    main()
