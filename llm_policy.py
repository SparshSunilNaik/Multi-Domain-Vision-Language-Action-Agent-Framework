"""
LLM-based stochastic policy using local Ollama (qwen3:8b).

Provides choose_action() that queries the LLM for element selection
and falls back to random choice on parse failure.
"""

import json
import random
import re
import time
import urllib.request
import urllib.error

OLLAMA_URL = "http://localhost:11434/api/generate"
MODEL_NAME = "qwen3:8b"
TEMPERATURE = 0.7
MAX_TOKENS = 20


def build_prompt(task_instruction, current_url, clickable_elements):
    """Build a minimal prompt for the LLM to choose one click action."""
    lines = []
    for i, el in enumerate(clickable_elements, 1):
        lines.append(f'{i}. click {el["role"]} "{el["name"]}"')
    action_list = "\n".join(lines) if lines else "(no actions available)"

    prompt = f"""You are a web navigation agent.

Task:
"{task_instruction}"

Current URL:
{current_url}

Available actions:
{action_list}

Choose exactly one action in this format:

click <number>

Only output the action.
Do not explain."""
    return prompt


def query_ollama(prompt):
    """Send prompt to Ollama and return the response text."""
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
        with urllib.request.urlopen(req, timeout=60) as resp:
            body = json.loads(resp.read().decode("utf-8"))
            return body.get("response", "")
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
        return f"ERROR: {e}"


def parse_action(response_text, clickable_elements):
    """Extract click target from LLM response. Fallback to random."""
    if not clickable_elements:
        return {"action": "click", "element_id": "", "parsed": False}

    # Try to find "click <number>"
    match = re.search(r"click\s+(\d+)", response_text, re.IGNORECASE)
    if match:
        idx = int(match.group(1))
        if 1 <= idx <= len(clickable_elements):
            el = clickable_elements[idx - 1]
            return {
                "action": "click",
                "element_id": el["id"],
                "element_name": el["name"],
                "element_role": el["role"],
                "choice_idx": idx,
                "parsed": True,
            }

    # Fallback: random valid element
    el = random.choice(clickable_elements)
    return {
        "action": "click",
        "element_id": el["id"],
        "element_name": el["name"],
        "element_role": el["role"],
        "choice_idx": -1,
        "parsed": False,
    }


def choose_action(task_instruction, current_url, clickable_elements):
    """Query LLM, parse action, return (action_dict, latency_seconds, raw_response)."""
    prompt = build_prompt(task_instruction, current_url, clickable_elements)

    t0 = time.time()
    raw = query_ollama(prompt)
    latency = time.time() - t0

    result = parse_action(raw, clickable_elements)
    result["llm_raw"] = raw.strip()[:80]
    result["latency"] = latency

    return result
