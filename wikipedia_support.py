"""
Wikipedia Domain Support — Completion detection and scenario definitions.

Provides Wikipedia-specific logic for the VLA evaluation system:
    - Completion detection (article loaded, search results, title match)
    - Predefined evaluation scenarios
    - Search term extraction from instructions
"""

import re

# ═══════════════════════════════════════════════════════════════
#  Predefined Wikipedia Scenarios
# ═══════════════════════════════════════════════════════════════
WIKIPEDIA_SCENARIOS = [
    {
        "instruction": "Search for Alan Turing on Wikipedia.",
        "start_url": "https://www.wikipedia.org",
        "search_term": "Alan Turing",
        "intent": "search",
    },
    {
        "instruction": "Find the page for Machine Learning.",
        "start_url": "https://www.wikipedia.org",
        "search_term": "Machine Learning",
        "intent": "find",
    },
    {
        "instruction": "Open Artificial Intelligence article.",
        "start_url": "https://www.wikipedia.org",
        "search_term": "Artificial Intelligence",
        "intent": "open",
    },
]

# ═══════════════════════════════════════════════════════════════
#  Intent Classification
# ═══════════════════════════════════════════════════════════════
SEARCH_KEYWORDS = {"search", "look up", "lookup", "query", "find results"}
NAVIGATE_KEYWORDS = {"open", "find", "go to", "navigate", "read", "visit",
                     "show", "display"}


def classify_intent(instruction):
    """Classify instruction intent: 'search' or 'navigate'."""
    instr_lower = instruction.lower()
    for kw in SEARCH_KEYWORDS:
        if kw in instr_lower:
            return "search"
    for kw in NAVIGATE_KEYWORDS:
        if kw in instr_lower:
            return "navigate"
    return "navigate"  # default


def extract_search_term(instruction):
    """Extract the topic/search term from an instruction.

    Handles patterns like:
        - "Search for Alan Turing on Wikipedia."
        - "Find the page for Machine Learning."
        - "Open Artificial Intelligence article."
    """
    instr = instruction.strip().rstrip(".")

    # "Search for X on Wikipedia"
    m = re.search(r'(?:search|look up|find|query)\s+(?:for\s+)?(.+?)(?:\s+on\s+wikipedia|\s+in\s+wikipedia|\s+article)?$',
                  instr, re.IGNORECASE)
    if m:
        term = m.group(1).strip()
        # Clean trailing noise
        term = re.sub(r'\s+on\s+wikipedia$', '', term, flags=re.IGNORECASE)
        term = re.sub(r'\s+page$', '', term, flags=re.IGNORECASE)
        term = re.sub(r'\s+article$', '', term, flags=re.IGNORECASE)
        term = re.sub(r'^the\s+page\s+for\s+', '', term, flags=re.IGNORECASE)
        term = re.sub(r'^the\s+', '', term, flags=re.IGNORECASE)
        if term:
            return term

    # "Open X article"
    m = re.search(r'(?:open|read|visit|go to|navigate to)\s+(?:the\s+)?(.+?)(?:\s+article|\s+page)?$',
                  instr, re.IGNORECASE)
    if m:
        term = m.group(1).strip()
        term = re.sub(r'\s+on\s+wikipedia$', '', term, flags=re.IGNORECASE)
        if term:
            return term

    # Fallback: take everything after the verb
    words = instr.split()
    if len(words) > 1:
        return " ".join(words[1:])
    return instr


# ═══════════════════════════════════════════════════════════════
#  Completion Detection
# ═══════════════════════════════════════════════════════════════

def _normalize(text):
    """Lowercase, strip punctuation, collapse whitespace."""
    return re.sub(r'[^a-z0-9\s]', '', text.lower()).strip()


def check_wikipedia_completion(instruction, current_url, page_title=""):
    """Check if the Wikipedia task has been completed.

    Returns (completed: bool, reason: str).
    """
    intent = classify_intent(instruction)
    search_term = extract_search_term(instruction)
    norm_term = _normalize(search_term)
    url_lower = current_url.lower()

    # ── Article page loaded ──
    if "/wiki/" in url_lower:
        # Extract article slug from URL
        wiki_path = url_lower.split("/wiki/")[-1].split("?")[0].split("#")[0]
        wiki_slug = wiki_path.replace("_", " ").replace("%20", " ")
        wiki_slug_norm = _normalize(wiki_slug)

        # Check if slug matches search term
        if norm_term and (norm_term in wiki_slug_norm
                         or wiki_slug_norm in norm_term):
            return True, f"Article page matched: /wiki/{wiki_path}"

        # For "open" or "find" intent, any matching article is success
        if intent in ("navigate", "open", "find"):
            # Check page title too
            if page_title:
                title_norm = _normalize(page_title)
                if norm_term and (norm_term in title_norm
                                 or title_norm in norm_term):
                    return True, f"Page title matched: {page_title}"

        # Even partial slug match counts
        term_words = norm_term.split()
        if term_words:
            matching_words = sum(1 for w in term_words if w in wiki_slug_norm)
            if matching_words >= len(term_words) * 0.5:
                return True, f"Partial article match: {wiki_slug}"

    # ── Search results page ──
    if intent == "search":
        if ("search" in url_lower and "wikipedia" in url_lower):
            return True, "Search results page loaded"
        if "Special:Search" in current_url:
            return True, "Special:Search page loaded"
        # Wikipedia sometimes redirects search to article directly
        if "/wiki/" in url_lower:
            return True, "Search redirected to article"

    # ── English Wikipedia article for navigate intent ──
    if intent == "navigate" and "/wiki/" in url_lower:
        # If we're on any wiki article page, consider partial success
        # (the LLM navigated to an article, even if not exact)
        return True, "Navigated to a wiki article"

    return False, "Not yet completed"


def get_page_title(page):
    """Extract the page title from a Playwright page."""
    try:
        return page.title()
    except Exception:
        return ""
