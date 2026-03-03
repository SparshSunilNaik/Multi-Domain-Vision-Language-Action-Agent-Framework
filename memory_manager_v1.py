"""
Memory Manager v1 — Persistent user profile for VLA agent.

CRUD operations on memory_store.json + deterministic regex extraction
from natural language instructions. NO LLM used for memory extraction.

Functions:
    load_memory()
    save_memory(memory_dict)
    update_memory(key, value)
    get_memory(key)
    extract_memory_from_user_instruction(instruction)
    enrich_instruction(instruction, memory)
    format_profile(memory)
    detect_autofills(trace_data, memory)
"""

import json
import os
import re
from datetime import datetime

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
MEMORY_FILE = os.path.join(SCRIPT_DIR, "memory_store.json")

DEFAULT_MEMORY = {
    "name": "Sparsh",
    "email": "sparsh@test.com",
    "phone": "1234567890",
    "address": "123 Wall Street",
    "city": "New York",
    "zip": "10005",
    "country": "USA",
}

# Log of all memory changes (in-memory, reset per session)
_memory_log = []


# ═══════════════════════════════════════════════════════════════
#  CRUD
# ═══════════════════════════════════════════════════════════════
def load_memory():
    """Load memory from disk. Creates default if missing."""
    if os.path.exists(MEMORY_FILE):
        try:
            with open(MEMORY_FILE) as f:
                stored = json.load(f)
            merged = dict(DEFAULT_MEMORY)
            merged.update(stored)
            return merged
        except (json.JSONDecodeError, IOError):
            pass
    save_memory(DEFAULT_MEMORY)
    return dict(DEFAULT_MEMORY)


def save_memory(memory_dict):
    """Persist memory to disk."""
    with open(MEMORY_FILE, "w") as f:
        json.dump(memory_dict, f, indent=2)


def update_memory(key, value):
    """Update a single key and persist."""
    mem = load_memory()
    old = mem.get(key)
    mem[key] = value
    save_memory(mem)
    ts = datetime.now().strftime("%H:%M:%S")
    log_entry = {
        "time": ts, "key": key, "old": old, "new": value,
    }
    _memory_log.append(log_entry)
    change = f" (was: {old})" if old and old != value else ""
    print(f"  MEMORY UPDATED: {key}={value}{change}")
    return mem


def get_memory(key):
    """Get a single key from memory."""
    return load_memory().get(key)


def get_memory_log():
    """Return all memory change entries for this session."""
    return list(_memory_log)


# ═══════════════════════════════════════════════════════════════
#  Regex Extraction from Instructions
# ═══════════════════════════════════════════════════════════════
MEMORY_PATTERNS = {
    "name": [
        # Match "My name is First Last" — stop at "and" or period
        r"[Mm]y\s+name\s+is\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)",
    ],
    "email": [
        r"(?:my\s+email\s+is|email:\s*|email\s+)\s*([\w.+\-]+@[\w.\-]+\.\w+)",
    ],
    "phone": [
        r"(?:my\s+phone(?:\s+number)?\s+is|phone:\s*)\s*([\d\s\-\+\(\)]{7,20})",
    ],
    "address": [
        # Match "my address is 123 Main St" — stop at "and my" or period or end
        r"(?:my\s+address\s+is|address:\s*)\s*(.+?)(?=\s+and\s+my\s|\s+and\s+[a-z]|\.$|$)",
    ],
    "city": [
        r"(?:my\s+city\s+is|city:\s*)\s*([A-Za-z][a-zA-Z\s]+?)(?=\s+and\s|\.$|$)",
    ],
    "zip": [
        r"(?:my\s+zip(?:\s+code)?\s+is|zip:\s*)\s*(\d{4,10})",
    ],
    "country": [
        r"(?:my\s+country\s+is|country:\s*)\s*([A-Za-z][a-zA-Z\s]+?)(?=\s+and\s|\.$|$)",
    ],
}


def extract_memory_from_user_instruction(instruction):
    """Extract user profile fields from instruction using REGEX ONLY.

    Returns dict of {key: value} for fields found.
    Side-effect: updates memory_store.json for each detected field.
    """
    if not instruction:
        return {}

    updates = {}
    for key, patterns in MEMORY_PATTERNS.items():
        for pattern in patterns:
            # Name pattern is case-sensitive to detect proper nouns;
            # others use IGNORECASE for flexibility
            flags = 0 if key == "name" else re.IGNORECASE
            m = re.search(pattern, instruction, flags)
            if m:
                val = m.group(1).strip().rstrip(".")
                if val and len(val) > 1:
                    updates[key] = val
                    break

    if updates:
        for k, v in updates.items():
            update_memory(k, v)

    return updates


# ═══════════════════════════════════════════════════════════════
#  Instruction Enrichment
# ═══════════════════════════════════════════════════════════════
PROFILE_KEYS = ["name", "email", "phone", "address", "city", "zip", "country"]


def format_profile(memory):
    """Format memory as a readable profile block."""
    lines = []
    for k in PROFILE_KEYS:
        if k in memory and memory[k]:
            lines.append(f"  - {k}: {memory[k]}")
    return "\n".join(lines) if lines else "  (empty)"


def enrich_instruction(instruction, memory):
    """Append memory profile to an instruction for form auto-fill.

    The LLM will use these values when filling matching form fields.
    """
    if not memory:
        return instruction

    parts = []
    for k in PROFILE_KEYS:
        v = memory.get(k)
        if v:
            parts.append(f"{k}={v}")

    if not parts:
        return instruction

    return (f"{instruction}\n"
            f"When filling forms, use these personal details: {', '.join(parts)}.")


# ═══════════════════════════════════════════════════════════════
#  Auto-fill Detection (post-hoc trace analysis)
# ═══════════════════════════════════════════════════════════════
FIELD_MEMORY_MAP = {
    "name": "name", "fullname": "name", "full_name": "name",
    "email": "email", "mail": "email",
    "phone": "phone", "tel": "phone", "telephone": "phone",
    "address": "address", "street": "address",
    "city": "city",
    "zip": "zip", "zipcode": "zip", "postal": "zip",
    "country": "country",
}


def detect_autofills(trace_data, memory):
    """Analyze a trace to find TYPE actions that used memory values.

    Returns list of {field, memory_key, value, step} dicts.
    """
    autofills = []
    if not trace_data or not memory:
        return autofills

    mem_values = {v.lower(): k for k, v in memory.items() if v}

    for step in trace_data.get("steps", []):
        if step.get("action_type") != "TYPE":
            continue
        typed_text = (step.get("typed_text", "") or "").strip()
        field_name = (step.get("field_name", "") or step.get("action_desc", "")).lower()

        if not typed_text:
            continue

        # Check if typed value matches a memory value
        typed_lower = typed_text.lower()
        if typed_lower in mem_values:
            mem_key = mem_values[typed_lower]
            autofills.append({
                "field": field_name[:30],
                "memory_key": mem_key,
                "value": typed_text,
                "step": step.get("step", 0),
            })
            continue

        # Check if field name maps to a memory key and value matches
        for field_kw, mem_key in FIELD_MEMORY_MAP.items():
            if field_kw in field_name:
                mem_val = memory.get(mem_key, "")
                if mem_val and typed_lower == mem_val.lower():
                    autofills.append({
                        "field": field_name[:30],
                        "memory_key": mem_key,
                        "value": typed_text,
                        "step": step.get("step", 0),
                    })
                    break

    return autofills


# ═══════════════════════════════════════════════════════════════
#  Web Task Detection
# ═══════════════════════════════════════════════════════════════
WEB_KEYWORDS = [
    "search", "book", "buy", "purchase", "find", "open", "watch",
    "navigate", "go to", "click", "type", "fill", "checkout",
    "order", "reserve", "schedule", "look up", "browse",
]


def is_web_task(instruction):
    """Check if an instruction requires web interaction."""
    lower = instruction.lower()
    return any(kw in lower for kw in WEB_KEYWORDS)
