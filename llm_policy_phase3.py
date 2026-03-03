"""
LLM Policy — Phase 3 (Full Autonomy: Click + Free-Text TYPE).

The LLM may now generate arbitrary text for TYPE actions.
No SLOT restrictions. No allowlist constraints.

Reuses:
    - llm_policy.query_ollama (same model qwen3:8b, temperature 0.7)
    - type_support.find_typeable_elements (element extraction only)
"""

import random
import re
import time
import json
import urllib.request
import urllib.error

# ── Ollama config (same model & temperature as Phase 1/2) ──
OLLAMA_URL = "http://localhost:11434/api/generate"
MODEL_NAME = "qwen3:8b"
TEMPERATURE = 0.7
MAX_TOKENS = 80  # increased from 20 to allow free-text generation

MAX_TEXT_LENGTH = 80  # hard cap on typed text


# ═══════════════════════════════════════════════════════════════
#  Ollama Query (standalone — allows different MAX_TOKENS)
# ═══════════════════════════════════════════════════════════════

def _query_ollama(prompt):
    """Send prompt to Ollama and return response text."""
    payload = json.dumps({
        "model": MODEL_NAME,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": TEMPERATURE,
            "num_predict": MAX_TOKENS,
        },
    }).encode("utf-8")

    req = urllib.request.Request(
        OLLAMA_URL,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=90) as resp:
            body = json.loads(resp.read().decode("utf-8"))
            return body.get("response", "")
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
        return f"ERROR: {e}"


# ═══════════════════════════════════════════════════════════════
#  Prompt Builder
# ═══════════════════════════════════════════════════════════════

def build_prompt_phase3(task_instruction, current_url,
                        clickable_elements, typeable_elements):
    """Build prompt that allows CLICK and free-text TYPE."""

    click_lines = []
    for el in clickable_elements:
        click_lines.append(f'  [{el["id"]}] {el["role"]} "{el["name"]}"')

    type_lines = []
    for el in typeable_elements:
        type_lines.append(f'  [{el["id"]}] {el["role"]} "{el["name"]}"')

    click_section = "\n".join(click_lines) if click_lines else "  (none)"
    type_section = "\n".join(type_lines) if type_lines else "  (none)"

    prompt = f"""You are a web navigation agent. Complete the task by clicking links/buttons or typing text into fields. You may submit forms.

Task:
"{task_instruction}"

Current URL:
{current_url}

Clickable elements:
{click_section}

Typeable elements:
{type_section}

Choose exactly one action. Format:

CLICK <id>
or
TYPE <id> "<text>"

Output only the action. Do not explain."""

    return prompt


# ═══════════════════════════════════════════════════════════════
#  Response Parser
# ═══════════════════════════════════════════════════════════════

def _sanitize_text(text):
    """Sanitize typed text: strip, remove newlines, cap length."""
    text = text.replace("\n", " ").replace("\r", " ").strip()
    if len(text) > MAX_TEXT_LENGTH:
        text = text[:MAX_TEXT_LENGTH]
    return text


def parse_action_phase3(response_text, clickable_elements,
                        typeable_elements):
    """Parse LLM response into a structured action.

    Returns dict with:
        type  — "CLICK" or "TYPE"
        id    — element id (str)
        name  — element name
        role  — element role
        text  — typed text (for TYPE) or None
        parsed — True if LLM output was parsed successfully
    """
    all_elements = clickable_elements + typeable_elements
    if not all_elements:
        return {
            "type": "CLICK", "id": "", "name": "", "role": "",
            "text": None, "parsed": False,
        }

    # Build ID lookup
    id_map = {}
    for el in all_elements:
        id_map[str(el["id"])] = el

    # ── Try TYPE pattern: TYPE <id> "<text>" ──
    type_match = re.search(
        r'TYPE\s+(\S+)\s+"([^"]*)"',
        response_text, re.IGNORECASE,
    )
    if not type_match:
        # Also try single quotes
        type_match = re.search(
            r"TYPE\s+(\S+)\s+'([^']*)'",
            response_text, re.IGNORECASE,
        )
    if not type_match:
        # Try without quotes (single word)
        type_match = re.search(
            r'TYPE\s+(\S+)\s+(\S+)',
            response_text, re.IGNORECASE,
        )

    if type_match:
        elem_id = type_match.group(1).strip("[]")
        raw_text = type_match.group(2)
        text = _sanitize_text(raw_text)

        if elem_id in id_map and text:
            el = id_map[elem_id]
            return {
                "type": "TYPE",
                "id": el["id"],
                "name": el["name"],
                "role": el["role"],
                "text": text,
                "parsed": True,
            }

    # ── Try CLICK pattern: CLICK <id> ──
    click_match = re.search(
        r'CLICK\s+(\S+)',
        response_text, re.IGNORECASE,
    )
    if click_match:
        elem_id = click_match.group(1).strip("[]").strip('"').strip("'")
        if elem_id in id_map:
            el = id_map[elem_id]
            return {
                "type": "CLICK",
                "id": el["id"],
                "name": el["name"],
                "role": el["role"],
                "text": None,
                "parsed": True,
            }

    # ── Fallback: random CLICK ──
    if clickable_elements:
        el = random.choice(clickable_elements)
    else:
        el = random.choice(all_elements)
    return {
        "type": "CLICK",
        "id": el["id"],
        "name": el["name"],
        "role": el["role"],
        "text": None,
        "parsed": False,
    }


# ═══════════════════════════════════════════════════════════════
#  Main Entry Point
# ═══════════════════════════════════════════════════════════════

def choose_action_phase3(task_instruction, current_url,
                         clickable_elements, typeable_elements):
    """Query LLM for free-form action, parse, return result dict."""
    prompt = build_prompt_phase3(
        task_instruction, current_url,
        clickable_elements, typeable_elements,
    )

    t0 = time.time()
    raw = _query_ollama(prompt)
    latency = time.time() - t0

    result = parse_action_phase3(raw, clickable_elements, typeable_elements)
    result["llm_raw"] = raw.strip()[:120]
    result["latency"] = latency

    return result
