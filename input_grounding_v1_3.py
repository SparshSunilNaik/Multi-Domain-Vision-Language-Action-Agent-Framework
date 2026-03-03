"""
Input Grounding Layer v1.3 — Deterministic normalization for form fields.

Converts natural-language LLM output into structured values expected by
HTML input types (date, number, email, etc.).

Functions:
    normalize_date(text)   → YYYY-MM-DD
    normalize_number(text) → numeric string
    normalize_email(text)  → valid email
    resolve_input(field_type, field_name, text) → normalized string
"""

import re
from datetime import datetime, timedelta

# ═══════════════════════════════════════════════════════════════
#  Date Normalization
# ═══════════════════════════════════════════════════════════════
WEEKDAY_MAP = {
    "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
    "friday": 4, "saturday": 5, "sunday": 6,
    "mon": 0, "tue": 1, "wed": 2, "thu": 3,
    "fri": 4, "sat": 5, "sun": 6,
}

def _next_weekday(today, target_weekday):
    """Compute the date of the next occurrence of target_weekday (0=Mon)."""
    days_ahead = target_weekday - today.weekday()
    if days_ahead <= 0:
        days_ahead += 7
    return today + timedelta(days=days_ahead)


def normalize_date(text):
    """Convert natural language date to YYYY-MM-DD.

    Handles:
        tomorrow, today, yesterday
        next Monday/Tuesday/etc
        in N days / N days from now
        next week
        YYYY-MM-DD (passthrough)
        MM/DD/YYYY, DD-MM-YYYY variations
    """
    if not text or not isinstance(text, str):
        return text

    t = text.strip().lower()
    today = datetime.now()

    # Already valid YYYY-MM-DD
    if re.match(r'^\d{4}-\d{2}-\d{2}$', t):
        return t

    # MM/DD/YYYY or DD/MM/YYYY (assume MM/DD/YYYY for US)
    m = re.match(r'^(\d{1,2})[/\-](\d{1,2})[/\-](\d{4})$', t)
    if m:
        try:
            dt = datetime(int(m.group(3)), int(m.group(1)), int(m.group(2)))
            return dt.strftime("%Y-%m-%d")
        except ValueError:
            pass

    # "today"
    if t in ("today", "now"):
        return today.strftime("%Y-%m-%d")

    # "tomorrow"
    if t in ("tomorrow", "tmrw", "tmr"):
        return (today + timedelta(days=1)).strftime("%Y-%m-%d")

    # "yesterday"
    if t == "yesterday":
        return (today - timedelta(days=1)).strftime("%Y-%m-%d")

    # "next week"
    if t in ("next week", "in a week", "in one week"):
        return (today + timedelta(days=7)).strftime("%Y-%m-%d")

    # "next Monday", "next tuesday", etc.
    m = re.match(r'(?:next\s+)?(\w+)', t)
    if m:
        day_name = m.group(1).lower()
        if day_name in WEEKDAY_MAP:
            target = WEEKDAY_MAP[day_name]
            dt = _next_weekday(today, target)
            return dt.strftime("%Y-%m-%d")

    # "in N days" or "N days from now" or "N days later"
    m = re.search(r'(\d+)\s*days?\s*(?:from\s*now|later|ahead)?', t)
    if m:
        n = int(m.group(1))
        return (today + timedelta(days=min(n, 365))).strftime("%Y-%m-%d")

    # "in N weeks"
    m = re.search(r'(\d+)\s*weeks?\s*(?:from\s*now|later)?', t)
    if m:
        n = int(m.group(1))
        return (today + timedelta(weeks=min(n, 52))).strftime("%Y-%m-%d")

    # Try parsing common date strings
    for fmt in ("%B %d, %Y", "%b %d, %Y", "%B %d %Y", "%d %B %Y",
                "%m/%d/%Y", "%d-%m-%Y", "%Y/%m/%d"):
        try:
            dt = datetime.strptime(t, fmt)
            return dt.strftime("%Y-%m-%d")
        except ValueError:
            continue

    # Fallback: return tomorrow (reasonable default for booking)
    return (today + timedelta(days=1)).strftime("%Y-%m-%d")


# ═══════════════════════════════════════════════════════════════
#  Number Normalization
# ═══════════════════════════════════════════════════════════════
WORD_NUMS = {
    "zero": "0", "one": "1", "two": "2", "three": "3", "four": "4",
    "five": "5", "six": "6", "seven": "7", "eight": "8", "nine": "9",
    "ten": "10", "eleven": "11", "twelve": "12", "thirteen": "13",
    "fourteen": "14", "fifteen": "15", "twenty": "20", "thirty": "30",
    "forty": "40", "fifty": "50", "hundred": "100",
}

def normalize_number(text):
    """Strip $, commas, convert word-numbers to digits."""
    if not text or not isinstance(text, str):
        return text
    t = text.strip().lower()
    # Remove currency symbols and commas
    t = re.sub(r'[$€£¥,]', '', t).strip()
    # Check if already numeric
    if re.match(r'^-?\d+\.?\d*$', t):
        return t
    # Word to number
    if t in WORD_NUMS:
        return WORD_NUMS[t]
    return text.strip()


# ═══════════════════════════════════════════════════════════════
#  Email Normalization
# ═══════════════════════════════════════════════════════════════
def normalize_email(text):
    """Validate email format; generate fallback if invalid."""
    if not text or not isinstance(text, str):
        return text
    t = text.strip()
    if re.match(r'^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$', t):
        return t
    # Try to extract email from text
    m = re.search(r'[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}', t)
    if m:
        return m.group(0)
    # Generate fallback
    ts = int(datetime.now().timestamp()) % 100000
    return f"user_{ts}@test.com"


# ═══════════════════════════════════════════════════════════════
#  Phone Normalization
# ═══════════════════════════════════════════════════════════════
def normalize_phone(text):
    """Strip non-digit chars except + prefix."""
    if not text or not isinstance(text, str):
        return text
    digits = re.sub(r'[^\d+]', '', text.strip())
    return digits if digits else text.strip()


# ═══════════════════════════════════════════════════════════════
#  Main Router
# ═══════════════════════════════════════════════════════════════
def resolve_input(field_type, field_name, text):
    """Route to the appropriate normalizer based on field type/name.

    Args:
        field_type: HTML input type (date, email, number, tel, text, etc.)
        field_name: Field name/label/placeholder (used for heuristic detection)
        text: Raw LLM output text

    Returns:
        Normalized text string
    """
    ft = (field_type or "").lower()
    fn = (field_name or "").lower()

    # Explicit type routing
    if ft == "date":
        return normalize_date(text)

    if ft == "email":
        return normalize_email(text)

    if ft == "number":
        return normalize_number(text)

    if ft in ("tel", "phone"):
        return normalize_phone(text)

    # Heuristic: field name suggests a type
    if any(k in fn for k in ("date", "booking_date", "appointment", "checkin",
                              "checkout", "schedule", "when")):
        return normalize_date(text)

    if any(k in fn for k in ("email", "e-mail", "mail")):
        return normalize_email(text)

    if any(k in fn for k in ("phone", "tel", "mobile", "cell")):
        return normalize_phone(text)

    if any(k in fn for k in ("amount", "price", "quantity", "qty", "count")):
        return normalize_number(text)

    # No transformation needed
    return text
