"""
LLM Policy — Phase 3B (Instruction-Conditioned, Goal-Directed Autonomy).

Upgrades over Phase 3A:
    1. Planning scaffold: PLAN + ACTION format
    2. Action history: last 3 actions shown in prompt
    3. TYPE promotion: instruction keywords reorder elements
    4. Goal alignment: lexical instruction–element matching

Reuses: llm_policy_phase3._query_ollama (same model qwen3:8b, temp 0.7)
"""

import json
import random
import re
import time
import urllib.request
import urllib.error

# ── Ollama config (same model & temperature) ──
OLLAMA_URL = "http://localhost:11434/api/generate"
MODEL_NAME = "qwen3:8b"
TEMPERATURE = 0.7
MAX_TOKENS = 120  # increased for PLAN + ACTION output
MAX_TEXT_LENGTH = 80

# ── TYPE promotion keywords ──
TYPE_KEYWORDS = {"search", "create", "name", "enter", "login", "type",
                 "write", "fill", "input", "register", "title", "comment",
                 "post", "describe", "label", "tag", "branch", "file"}


# ═══════════════════════════════════════════════════════════════
#  Ollama Query
# ═══════════════════════════════════════════════════════════════

def _query_ollama(prompt):
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
#  TYPE Promotion Logic
# ═══════════════════════════════════════════════════════════════

def should_promote_type(instruction):
    """Check if instruction contains keywords that suggest typing."""
    instr_lower = instruction.lower()
    return any(kw in instr_lower for kw in TYPE_KEYWORDS)


def get_instruction_keywords(instruction):
    """Extract significant words from instruction for alignment scoring."""
    stop_words = {
        "the", "a", "an", "is", "are", "was", "were", "be", "been",
        "being", "have", "has", "had", "do", "does", "did", "will",
        "would", "could", "should", "may", "might", "can", "shall",
        "to", "of", "in", "for", "on", "with", "at", "by", "from",
        "and", "or", "but", "not", "if", "then", "else", "when",
        "where", "how", "what", "which", "who", "whom", "this",
        "that", "these", "those", "i", "me", "my", "we", "our",
        "you", "your", "he", "she", "it", "they", "them", "its",
        "all", "each", "every", "both", "few", "more", "most",
        "some", "any", "no", "as", "so", "than", "too", "very",
        "just", "about", "up", "out", "into", "over", "after",
        "before", "between", "under", "above", "below", "tell",
        "find", "check", "go", "get", "see", "look", "show",
    }
    words = re.findall(r'\b[a-zA-Z]{3,}\b', instruction.lower())
    return [w for w in words if w not in stop_words]


# ═══════════════════════════════════════════════════════════════
#  Prompt Builder
# ═══════════════════════════════════════════════════════════════

def build_prompt_phase3b(task_instruction, current_url,
                         clickable_elements, typeable_elements,
                         action_history=None):
    """Build goal-directed prompt with planning scaffold."""

    promote_type = should_promote_type(task_instruction)

    # ── Element sections ──
    click_lines = []
    for el in clickable_elements:
        click_lines.append(f'  [{el["id"]}] {el["role"]} "{el["name"]}"')

    type_lines = []
    for el in typeable_elements:
        type_lines.append(f'  [{el["id"]}] {el["role"]} "{el["name"]}"')

    click_section = "\n".join(click_lines) if click_lines else "  (none)"
    type_section = "\n".join(type_lines) if type_lines else "  (none)"

    # ── Action history ──
    history_text = ""
    if action_history:
        recent = action_history[-3:]
        history_lines = [f"  {i+1}. {a}" for i, a in enumerate(recent)]
        history_text = f"\nRecent actions:\n" + "\n".join(history_lines)

    # ── Order: promote TYPE before CLICK if instruction suggests typing ──
    if promote_type and type_lines:
        elements_section = (
            f"Typeable elements (you can type text here):\n{type_section}\n\n"
            f"Clickable elements:\n{click_section}"
        )
    else:
        elements_section = (
            f"Clickable elements:\n{click_section}\n\n"
            f"Typeable elements:\n{type_section}"
        )

    prompt = f"""You are a web navigation agent working toward a specific goal.

GOAL:
"{task_instruction}"

Current URL:
{current_url}
{history_text}

{elements_section}

Think about what action will best advance toward the GOAL.

Respond in exactly this format:

PLAN: <one sentence describing what to do next and why>
ACTION: CLICK <id>
or
PLAN: <one sentence describing what to do next and why>
ACTION: TYPE <id> "<text>"

Output only the PLAN and ACTION lines. Nothing else."""

    return prompt


# ═══════════════════════════════════════════════════════════════
#  Response Parser
# ═══════════════════════════════════════════════════════════════

def _sanitize_text(text):
    text = text.replace("\n", " ").replace("\r", " ").strip()
    if len(text) > MAX_TEXT_LENGTH:
        text = text[:MAX_TEXT_LENGTH]
    return text


def parse_action_phase3b(response_text, clickable_elements,
                         typeable_elements):
    """Parse PLAN + ACTION from LLM response.

    Returns dict with:
        type, id, name, role, text, parsed, plan
    """
    all_elements = clickable_elements + typeable_elements
    if not all_elements:
        return {
            "type": "CLICK", "id": "", "name": "", "role": "",
            "text": None, "parsed": False, "plan": "",
        }

    # ID lookup
    id_map = {}
    for el in all_elements:
        id_map[str(el["id"])] = el

    # ── Extract PLAN ──
    plan = ""
    plan_match = re.search(r'PLAN:\s*(.+?)(?:\n|ACTION:|$)',
                           response_text, re.IGNORECASE | re.DOTALL)
    if plan_match:
        plan = plan_match.group(1).strip()[:200]

    # ── Extract ACTION — try TYPE first ──
    type_match = re.search(
        r'ACTION:\s*TYPE\s+(\S+)\s+"([^"]*)"',
        response_text, re.IGNORECASE,
    )
    if not type_match:
        type_match = re.search(
            r"ACTION:\s*TYPE\s+(\S+)\s+'([^']*)'",
            response_text, re.IGNORECASE,
        )
    if not type_match:
        # Try without ACTION: prefix
        type_match = re.search(
            r'TYPE\s+(\S+)\s+"([^"]*)"',
            response_text, re.IGNORECASE,
        )
    if not type_match:
        type_match = re.search(
            r"TYPE\s+(\S+)\s+'([^']*)'",
            response_text, re.IGNORECASE,
        )
    if not type_match:
        # Single word without quotes
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
                "plan": plan,
            }

    # ── Try CLICK ──
    click_match = re.search(
        r'ACTION:\s*CLICK\s+(\S+)',
        response_text, re.IGNORECASE,
    )
    if not click_match:
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
                "plan": plan,
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
        "plan": plan,
    }


# ═══════════════════════════════════════════════════════════════
#  Goal Alignment Scorer
# ═══════════════════════════════════════════════════════════════

def compute_goal_alignment(instruction, elem_name, action_type, typed_text):
    """Simple lexical alignment: count instruction keywords in element/text."""
    keywords = get_instruction_keywords(instruction)
    if not keywords:
        return 0.0

    target_text = elem_name.lower()
    if typed_text:
        target_text += " " + typed_text.lower()

    matches = sum(1 for kw in keywords if kw in target_text)
    return round(matches / len(keywords), 3)


# ═══════════════════════════════════════════════════════════════
#  Main Entry Point
# ═══════════════════════════════════════════════════════════════

def choose_action_phase3b(task_instruction, current_url,
                          clickable_elements, typeable_elements,
                          action_history=None):
    """Query LLM with planning scaffold, parse PLAN + ACTION."""
    prompt = build_prompt_phase3b(
        task_instruction, current_url,
        clickable_elements, typeable_elements,
        action_history,
    )

    t0 = time.time()
    raw = _query_ollama(prompt)
    latency = time.time() - t0

    result = parse_action_phase3b(raw, clickable_elements, typeable_elements)
    result["llm_raw"] = raw.strip()[:160]
    result["latency"] = latency

    # Goal alignment
    result["goal_alignment"] = compute_goal_alignment(
        task_instruction,
        result.get("name", ""),
        result["type"],
        result.get("text"),
    )

    return result
