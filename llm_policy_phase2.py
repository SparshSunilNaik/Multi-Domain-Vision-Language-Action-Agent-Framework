"""
LLM Policy — Phase 2 (Click + Structured TYPE).

Extends the Phase 1 click-only policy to also propose TYPE actions
using a controlled SLOT allowlist.  No arbitrary free-text generation.

Reuses:
    - llm_policy.query_ollama (same model, temperature, max_tokens)
    - type_support.find_typeable_elements, SLOT_NAMES, resolve_slot
"""

import random
import re
import time

from llm_policy import query_ollama          # reuse Ollama HTTP client
from type_support import SLOT_NAMES          # controlled slot names


# ═══════════════════════════════════════════════════════════════
#  Prompt Builder
# ═══════════════════════════════════════════════════════════════

def build_prompt_phase2(task_instruction, current_url,
                        clickable_elements, typeable_elements):
    """Build prompt that presents CLICK and TYPE options."""

    lines = []
    idx = 1

    # ── Clickable actions ──
    for el in clickable_elements:
        lines.append(f'{idx}. CLICK "{el["name"]}"')
        idx += 1

    # ── Typeable actions (one per slot per field) ──
    for el in typeable_elements:
        for slot in SLOT_NAMES:
            lines.append(f'{idx}. TYPE "{el["name"]}" {slot}')
            idx += 1

    action_list = "\n".join(lines) if lines else "(no actions available)"

    prompt = f"""You are a web navigation agent.

Task:
"{task_instruction}"

Current URL:
{current_url}

Available actions:
{action_list}

Choose exactly one action by its number:

<number>

Only output the number.
Do not explain."""
    return prompt, idx - 1  # return total action count


# ═══════════════════════════════════════════════════════════════
#  Action Index Mapping
# ═══════════════════════════════════════════════════════════════

def _build_action_map(clickable_elements, typeable_elements):
    """Build ordered list mapping 1-based index → action descriptor."""
    actions = []

    for el in clickable_elements:
        actions.append({
            "type": "CLICK",
            "id": el["id"],
            "name": el["name"],
            "role": el["role"],
            "slot": None,
        })

    for el in typeable_elements:
        for slot in SLOT_NAMES:
            actions.append({
                "type": "TYPE",
                "id": el["id"],
                "name": el["name"],
                "role": el["role"],
                "slot": slot,
            })

    return actions


# ═══════════════════════════════════════════════════════════════
#  Response Parser
# ═══════════════════════════════════════════════════════════════

def parse_action_phase2(response_text, clickable_elements,
                        typeable_elements):
    """Parse LLM response into a structured action.

    Returns dict with keys:
        type       — "CLICK" or "TYPE"
        id         — element id
        name       — element display name
        role       — element role
        slot       — slot name (for TYPE) or None
        choice_idx — 1-based index chosen by LLM
        parsed     — True if LLM output was parsed successfully
    """
    action_map = _build_action_map(clickable_elements, typeable_elements)

    if not action_map:
        return {
            "type": "CLICK", "id": "", "name": "", "role": "",
            "slot": None, "choice_idx": -1, "parsed": False,
        }

    # Try to extract number from response
    match = re.search(r"(\d+)", response_text)
    if match:
        idx = int(match.group(1))
        if 1 <= idx <= len(action_map):
            chosen = action_map[idx - 1]
            chosen["choice_idx"] = idx
            chosen["parsed"] = True
            return chosen

    # ── Fallback: random CLICK ──
    click_actions = [a for a in action_map if a["type"] == "CLICK"]
    if click_actions:
        chosen = random.choice(click_actions)
    else:
        chosen = random.choice(action_map)
    chosen["choice_idx"] = -1
    chosen["parsed"] = False
    return chosen


# ═══════════════════════════════════════════════════════════════
#  Main Entry Point
# ═══════════════════════════════════════════════════════════════

def choose_action_phase2(task_instruction, current_url,
                         clickable_elements, typeable_elements):
    """Query LLM, parse action, return result dict.

    Returns dict with:
        type, id, name, role, slot, choice_idx, parsed,
        llm_raw, latency
    """
    prompt, total_count = build_prompt_phase2(
        task_instruction, current_url,
        clickable_elements, typeable_elements,
    )

    t0 = time.time()
    raw = query_ollama(prompt)
    latency = time.time() - t0

    result = parse_action_phase2(raw, clickable_elements, typeable_elements)
    result["llm_raw"] = raw.strip()[:80]
    result["latency"] = latency

    return result
