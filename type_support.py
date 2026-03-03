"""
Phase 2 — Structured TYPE Support.

Provides:
    find_typeable_elements()  — extract typeable inputs from a11y tree
    SLOT_MAP                  — controlled allowlist of text values
    resolve_slot()            — validate and resolve slot names
"""

import time

# ═══════════════════════════════════════════════════════════════
#  Typeable Element Extraction
# ═══════════════════════════════════════════════════════════════

TYPEABLE_ROLES = {"textbox", "searchbox", "input"}


def find_typeable_elements(elements):
    """Extract elements whose role indicates a text-input field.

    Args:
        elements: list of dicts from parse_a11y_tree(), each with
                  {id, role, name, line}.

    Returns:
        list of {id, name, role} for typeable elements.
    """
    result = []
    for el in elements:
        if el["role"].lower() in TYPEABLE_ROLES:
            result.append({
                "id": el["id"],
                "name": el["name"],
                "role": el["role"],
            })
    return result


# ═══════════════════════════════════════════════════════════════
#  SLOT_MAP — Controlled Allowlist
# ═══════════════════════════════════════════════════════════════

def _ts():
    """Deterministic timestamp suffix to avoid collisions."""
    return str(int(time.time()))


SLOT_MAP = {
    "PROJECT_NAME":  lambda: f"phase2-project-{_ts()}",
    "SEARCH_QUERY":  lambda: "test",
    "ISSUE_TITLE":   lambda: f"phase2-issue-{_ts()}",
    "DESCRIPTION":   lambda: "phase2-description",
    "COMMENT_TEXT":   lambda: "phase2-comment",
    "TAG_NAME":      lambda: f"phase2-tag-{_ts()}",
    "BRANCH_NAME":   lambda: f"phase2-branch-{_ts()}",
    "LABEL_NAME":    lambda: f"phase2-label-{_ts()}",
    "FILENAME":      lambda: "phase2-file.txt",
    "USERNAME":      lambda: "phase2-user",
}

# Ordered list for prompt generation (static names only)
SLOT_NAMES = sorted(SLOT_MAP.keys())


# ═══════════════════════════════════════════════════════════════
#  Slot Resolver
# ═══════════════════════════════════════════════════════════════

def resolve_slot(slot_name):
    """Validate slot_name against SLOT_MAP and return the mapped string.

    Args:
        slot_name: e.g. "SEARCH_QUERY"

    Returns:
        Resolved string value.

    Raises:
        ValueError: if slot_name is not in SLOT_MAP.
    """
    key = slot_name.strip().upper()
    if key not in SLOT_MAP:
        raise ValueError(
            f"Unknown SLOT '{slot_name}'. "
            f"Allowed: {', '.join(SLOT_NAMES)}"
        )
    return SLOT_MAP[key]()
