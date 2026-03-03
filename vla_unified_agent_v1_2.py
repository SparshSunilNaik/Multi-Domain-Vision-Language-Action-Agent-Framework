#!/usr/bin/env python3
"""
Unified VLA Agent v1.2 — PLAN→ACTION Scaffold.

Key upgrades from v1.1:
  1. PLAN→ACTION prompt: LLM must plan before acting
  2. Planning memory: last 6 actions + last plan in context
  3. Plan adherence metric per step
  4. Missing-required-fields detection before form submit
  5. --visual flag for step-by-step visible debugging

Architecture: Ollama qwen3:8b, /api/chat, think:false,
data-vla-id injection, headless=False, no safety gating.

Usage:
    python vla_unified_agent_v1_2.py                          # Interactive
    python vla_unified_agent_v1_2.py --scenarios file.json    # Batch
    python vla_unified_agent_v1_2.py --builtin                # Built-in
    python vla_unified_agent_v1_2.py --scenarios f.json --visual  # Visual debug
"""

import argparse
import json
import os
import re
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime

# ═══════════════════════════════════════════════════════════════
#  Config
# ═══════════════════════════════════════════════════════════════
OLLAMA_URL       = "http://localhost:11434/api/chat"
MODEL_NAME       = "qwen3:8b"
TEMPERATURE      = 0.7
NUM_PREDICT      = 150  # Increased for PLAN+ACTION output
MAX_STEPS_DEFAULT = 20
MAX_CLICKABLE    = 20
MAX_TYPEABLE     = 5
MAX_TEXT_LEN     = 80
SAME_URL_LIMIT   = 12
MEMORY_SIZE      = 6  # last N actions to keep in prompt

GITLAB_USER = os.environ.get("GITLAB_USER", "")
GITLAB_PASS = os.environ.get("GITLAB_PASS", "")
SCRIPT_DIR  = os.path.dirname(os.path.abspath(__file__))

# ═══════════════════════════════════════════════════════════════
#  Built-in Scenarios
# ═══════════════════════════════════════════════════════════════
BUILTIN_SCENARIOS = [
    {"name": "Wikipedia — Alan Turing",
     "instruction": "Search for Alan Turing on Wikipedia.",
     "start_url": "https://en.wikipedia.org",
     "completion_keyword": "/wiki/Alan_Turing", "max_steps": 10},
    {"name": "YouTube — ML Basics",
     "instruction": "Search for 'machine learning basics'.",
     "start_url": "https://www.youtube.com",
     "completion_keyword": "results", "max_steps": 10},
    {"name": "GitHub — Open",
     "instruction": "Go to GitHub homepage.",
     "start_url": "https://github.com",
     "completion_keyword": "github.com", "max_steps": 5},
    {"name": "Google — OpenAI (captcha test)",
     "instruction": "Search for 'OpenAI' on Google.",
     "start_url": "https://www.google.com",
     "completion_keyword": "search?q=", "max_steps": 10},
]

# ═══════════════════════════════════════════════════════════════
#  JS DOM Extraction (v1.1 upgraded: radio/checkbox/select)
# ═══════════════════════════════════════════════════════════════
EXTRACT_JS = """
() => {
    const results = [];
    const seen = new Set();
    let counter = 0;

    function isVisible(el) {
        const check = (el.tagName === 'INPUT' &&
            (el.type === 'radio' || el.type === 'checkbox'))
            ? (el.parentElement || el) : el;
        if (!check.offsetParent && check.tagName !== 'BODY' && check.tagName !== 'HTML') return false;
        const r = check.getBoundingClientRect();
        if (r.width === 0 || r.height === 0) {
            if (el.tagName === 'INPUT' && (el.type === 'radio' || el.type === 'checkbox')) {
                const label = document.querySelector('label[for="' + el.id + '"]');
                if (label) { const lr = label.getBoundingClientRect(); if (lr.width > 0 && lr.height > 0) return true; }
                const pr = el.parentElement ? el.parentElement.getBoundingClientRect() : r;
                if (pr.width > 0 && pr.height > 0) return true;
            }
            return false;
        }
        if (r.bottom < 0 || r.top > window.innerHeight) return false;
        if (r.right < 0 || r.left > window.innerWidth) return false;
        const s = window.getComputedStyle(check);
        if (s.display === 'none' || s.visibility === 'hidden') return false;
        if (parseFloat(s.opacity) < 0.1) return false;
        return true;
    }

    function getLabel(el) {
        if (el.tagName === 'INPUT' && (el.type === 'radio' || el.type === 'checkbox')) {
            if (el.id) { const lbl = document.querySelector('label[for="' + el.id + '"]'); if (lbl) return lbl.textContent.trim().substring(0, 80); }
            const parentLabel = el.closest('label');
            if (parentLabel) return parentLabel.textContent.trim().substring(0, 80);
            if (el.nextSibling && el.nextSibling.textContent) { const t = el.nextSibling.textContent.trim().substring(0, 80); if (t) return t; }
        }
        if (el.tagName === 'SELECT') {
            const lbl = el.getAttribute('aria-label') || el.getAttribute('name') || el.getAttribute('id') || '';
            const sel = el.options && el.selectedIndex >= 0 ? el.options[el.selectedIndex].text : '';
            return (lbl ? lbl + (sel ? ' [' + sel + ']' : '') : sel).trim().substring(0, 80) || 'dropdown';
        }
        if (el.tagName === 'OPTION') return el.textContent.trim().substring(0, 80);
        return (el.getAttribute('aria-label') || el.getAttribute('title') || el.getAttribute('placeholder') || el.getAttribute('alt') || el.textContent.trim().substring(0, 80) || el.getAttribute('name') || el.getAttribute('id') || '').trim().replace(/\\s+/g, ' ').substring(0, 80);
    }

    function tag(el) { counter++; el.setAttribute('data-vla-id', String(counter)); return counter; }

    // Clickable
    document.querySelectorAll(
        'a[href], button, [role="button"], [role="link"], [role="menuitem"], [role="tab"], [role="option"], [onclick], summary, [role="treeitem"], input[type="radio"], input[type="checkbox"]'
    ).forEach(el => {
        if (!isVisible(el)) return;
        const label = getLabel(el);
        if (!label || label.length < 1) return;
        const inputType = el.getAttribute('type') || null;
        const key = 'c:' + (inputType || '') + ':' + label.toLowerCase().substring(0, 40);
        if (seen.has(key)) return;
        seen.add(key);
        const vid = tag(el);
        let role = el.getAttribute('role');
        if (!role) { if (el.tagName === 'A') role = 'link'; else if (inputType === 'radio') role = 'radio'; else if (inputType === 'checkbox') role = 'checkbox'; else role = 'button'; }
        results.push({ vla_id: vid, kind: 'clickable', tag: el.tagName.toLowerCase(), role: role, label: label, input_type: inputType, name: el.getAttribute('name') || null, el_id: el.getAttribute('id') || null });
    });

    // Select
    document.querySelectorAll('select').forEach(el => {
        if (!isVisible(el)) return;
        const label = getLabel(el);
        const vid = tag(el);
        const opts = [];
        if (el.options) { for (let i = 0; i < el.options.length && i < 10; i++) opts.push(el.options[i].text.trim().substring(0, 40)); }
        results.push({ vla_id: vid, kind: 'clickable', tag: 'select', role: 'listbox', label: label + (opts.length ? ' (' + opts.join(', ') + ')' : ''), input_type: 'select', name: el.getAttribute('name') || null, el_id: el.getAttribute('id') || null });
    });

    // Typeable
    document.querySelectorAll(
        'input[type="text"], input[type="search"], input[type="email"], input[type="password"], input[type="url"], input[type="tel"], input[type="number"], input[type="date"], input:not([type]), textarea, [contenteditable="true"], [role="textbox"], [role="searchbox"], [role="combobox"]'
    ).forEach(el => {
        if (!isVisible(el)) return;
        if (el.tagName === 'INPUT') { const t = (el.getAttribute('type') || '').toLowerCase(); if (t === 'radio' || t === 'checkbox' || t === 'hidden' || t === 'submit' || t === 'button') return; }
        const label = getLabel(el) || el.getAttribute('type') || 'text input';
        const key = 't:' + label.toLowerCase().substring(0, 40);
        if (seen.has(key)) return;
        seen.add(key);
        const vid = tag(el);
        results.push({ vla_id: vid, kind: 'typeable', tag: el.tagName.toLowerCase(), role: el.getAttribute('role') || 'textbox', label: label, input_type: el.getAttribute('type') || null, name: el.getAttribute('name') || null, el_id: el.getAttribute('id') || null, placeholder: el.getAttribute('placeholder') || null });
    });

    return results;
}
"""

# JS to detect empty required/visible form fields
CHECK_EMPTY_FIELDS_JS = """
() => {
    const empty = [];
    document.querySelectorAll('input, textarea, select').forEach(el => {
        if (!el.offsetParent) return;
        const t = (el.getAttribute('type') || '').toLowerCase();
        if (t === 'hidden' || t === 'submit' || t === 'button' || t === 'radio' || t === 'checkbox') return;
        const r = el.getBoundingClientRect();
        if (r.width === 0 || r.height === 0) return;
        const s = window.getComputedStyle(el);
        if (s.display === 'none' || s.visibility === 'hidden') return;
        const val = el.value ? el.value.trim() : '';
        if (!val) {
            const label = el.getAttribute('placeholder') || el.getAttribute('name') || el.getAttribute('id') || el.getAttribute('aria-label') || '';
            if (label) empty.push(label);
        }
    });
    return empty;
}
"""

# ═══════════════════════════════════════════════════════════════
#  Ollama /api/chat (think: false)
# ═══════════════════════════════════════════════════════════════
def llm_query(prompt, max_tokens=NUM_PREDICT):
    payload = json.dumps({
        "model": MODEL_NAME,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False, "think": False,
        "options": {"temperature": TEMPERATURE, "num_predict": max_tokens},
    }).encode()
    req = urllib.request.Request(OLLAMA_URL, data=payload,
        headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=90) as r:
            body = json.loads(r.read().decode())
            raw = body.get("message", {}).get("content", "").strip()
            return re.sub(r'<think>.*?</think>', '', raw, flags=re.DOTALL).strip()
    except Exception as e:
        return f"ERROR: {e}"


# ═══════════════════════════════════════════════════════════════
#  Element Extraction
# ═══════════════════════════════════════════════════════════════
def extract_elements(page):
    try:
        raw = page.evaluate(EXTRACT_JS)
    except Exception:
        return [], []
    if not raw:
        return [], []
    return ([e for e in raw if e["kind"] == "clickable"][:MAX_CLICKABLE],
            [e for e in raw if e["kind"] == "typeable"][:MAX_TYPEABLE])


def get_empty_fields(page):
    """Return list of empty visible form field names."""
    try:
        return page.evaluate(CHECK_EMPTY_FIELDS_JS) or []
    except Exception:
        return []


# ═══════════════════════════════════════════════════════════════
#  PLAN→ACTION Prompt Builder
# ═══════════════════════════════════════════════════════════════
def build_prompt(instruction, url, clickable, typeable, action_history,
                 last_plan, empty_fields, skip_ids):
    cl_lines = []
    for e in clickable:
        mark = " (already tried)" if skip_ids and str(e["vla_id"]) in skip_ids else ""
        cl_lines.append(f'  [{e["vla_id"]}] {e["role"]} "{e["label"]}"{mark}')
    cl = "\n".join(cl_lines) or "  (none)"

    tl = "\n".join(f'  [{e["vla_id"]}] {e["role"]} "{e["label"]}"'
                   for e in typeable) or "  (none)"

    # Action history (last N)
    hist = ""
    if action_history:
        recent = action_history[-MEMORY_SIZE:]
        hist_lines = [f"  {i+1}. {a}" for i, a in enumerate(recent)]
        hist = "\nRecent actions:\n" + "\n".join(hist_lines)

    # Last plan
    prev_plan = ""
    if last_plan:
        prev_plan = f"\nPrevious plan:\n{last_plan}"

    # Missing fields warning
    missing = ""
    if empty_fields:
        missing = ("\n⚠ UNFILLED FIELDS on this page: " +
                   ", ".join(empty_fields[:6]) +
                   "\nYou MUST fill ALL fields before clicking Submit/Confirm.")

    return f"""You are a web navigation agent. Complete the task step by step.

GOAL: "{instruction}"

Current URL: {url}{hist}{prev_plan}{missing}

Clickable elements:
{cl}

Typeable elements:
{tl}

INSTRUCTIONS:
1. First write a short PLAN (2-4 bullet points) of what to do next.
2. Then write exactly ONE action line.

Format your response EXACTLY like this:
PLAN:
- step one
- step two
ACTION: CLICK <id>

Or: ACTION: TYPE <id> "<text>"
Or: ACTION: STOP

IMPORTANT:
- Fill ALL form fields before clicking submit buttons.
- Select radio/checkbox options before clicking Next/Submit.
- Output the PLAN and ACTION only. Nothing else."""


# ═══════════════════════════════════════════════════════════════
#  Response Parser (extracts PLAN + ACTION)
# ═══════════════════════════════════════════════════════════════
def parse_response(response, clickable, typeable):
    """Parse PLAN and ACTION from LLM response."""
    all_el = {str(e["vla_id"]): e for e in clickable + typeable}

    # Extract PLAN
    plan = ""
    plan_match = re.search(r'PLAN:\s*\n((?:\s*-\s*.+\n?)+)', response, re.IGNORECASE)
    if plan_match:
        plan = plan_match.group(1).strip()

    # Extract ACTION line
    action_line = ""
    action_match = re.search(r'ACTION:\s*(.+)', response, re.IGNORECASE)
    if action_match:
        action_line = action_match.group(1).strip()
    else:
        # Fallback: look for raw CLICK/TYPE/STOP anywhere
        action_line = response.strip().split("\n")[-1]

    # Parse action
    if re.search(r'\bSTOP\b', action_line, re.IGNORECASE):
        return plan, {"type": "STOP"}

    for pat in [r'TYPE\s+(\S+)\s+"([^"]+)"',
                r"TYPE\s+(\S+)\s+'([^']+)'",
                r'TYPE\s+(\S+)\s+(.+)']:
        m = re.search(pat, action_line, re.IGNORECASE)
        if m:
            eid = m.group(1).strip("[]\"'")
            txt = m.group(2).replace("\n", " ").strip()[:MAX_TEXT_LEN]
            if eid in all_el and txt:
                return plan, {"type": "TYPE", "id": eid, "text": txt,
                              "element": all_el[eid]}
            break

    m = re.search(r'CLICK\s+(\S+)', action_line, re.IGNORECASE)
    if m:
        eid = m.group(1).strip("[]\"'")
        if eid in all_el:
            return plan, {"type": "CLICK", "id": eid, "element": all_el[eid]}

    # Fallback
    for e in typeable:
        if any(k in e["label"].lower() for k in ("search", "query")):
            return plan, {"type": "CLICK", "id": str(e["vla_id"]),
                          "element": e, "fallback": True}
    if clickable:
        return plan, {"type": "CLICK", "id": str(clickable[0]["vla_id"]),
                      "element": clickable[0], "fallback": True}
    return plan, {"type": "STOP"}


# ═══════════════════════════════════════════════════════════════
#  Plan Adherence Metric
# ═══════════════════════════════════════════════════════════════
STOP_WORDS = {"the", "a", "an", "to", "and", "or", "for", "in", "on", "of",
              "is", "it", "this", "that", "with", "as", "by", "at", "i", "we",
              "if", "then", "next", "step", "click", "type", "should", "need",
              "must", "will", "can", "do", "be", "have", "not", "all", "from"}

def extract_keywords(text):
    words = re.findall(r'[a-zA-Z]{3,}', text.lower())
    return {w for w in words if w not in STOP_WORDS}

def compute_adherence(plan, action_desc, url):
    """Score 0.0-1.0: how well the action matches the plan keywords."""
    if not plan:
        return 0.5  # neutral if no plan
    plan_kw = extract_keywords(plan)
    if not plan_kw:
        return 0.5
    context = (action_desc + " " + url).lower()
    matches = sum(1 for kw in plan_kw if kw in context)
    return round(min(matches / max(len(plan_kw), 1), 1.0), 2)


# ═══════════════════════════════════════════════════════════════
#  Conditional Enter (from v1.1)
# ═══════════════════════════════════════════════════════════════
def _should_enter(el):
    itype = (el.get("input_type") or "").lower()
    if itype == "search": return True
    for field in ("placeholder", "name", "el_id", "label"):
        val = (el.get(field) or "").lower()
        if "search" in val or val == "q": return True
    return False


# ═══════════════════════════════════════════════════════════════
#  Action Executor
# ═══════════════════════════════════════════════════════════════
def execute(page, action):
    if action["type"] == "STOP":
        return "STOP"
    el = action.get("element", {})
    vid = el.get("vla_id", "")
    sel = f'[data-vla-id="{vid}"]'
    label = el.get("label", "?")

    if action["type"] == "TYPE":
        text = action["text"]
        enter = _should_enter(el)
        try:
            h = page.query_selector(sel)
            if h:
                h.click(); time.sleep(0.1)
                h.fill(text); time.sleep(0.1)
                if enter:
                    h.press("Enter"); time.sleep(0.8)
                else:
                    time.sleep(0.3)
                return f'TYPE [{vid}] "{label}" ← "{text}"' + (" ⏎" if enter else "")
            page.keyboard.type(text, delay=25)
            if enter: page.keyboard.press("Enter"); time.sleep(0.5)
            return f'TYPE (kb) ← "{text}"'
        except Exception as e:
            try:
                page.keyboard.type(text, delay=25)
                if enter: page.keyboard.press("Enter"); time.sleep(0.5)
                return f'TYPE (kb-fb) ← "{text}"'
            except Exception:
                return f'TYPE FAIL: {str(e)[:40]}'

    if action["type"] == "CLICK":
        try:
            h = page.query_selector(sel)
            if h:
                h.scroll_into_view_if_needed(timeout=3000); time.sleep(0.1)
                h.click(timeout=5000); time.sleep(0.6)
                return f'CLICK [{vid}] "{label}"'
            loc = page.get_by_text(label, exact=False)
            if loc.count() > 0:
                loc.first.click(timeout=5000); time.sleep(0.5)
                return f'CLICK (text) "{label}"'
            return f'CLICK SKIP: "{label}"'
        except Exception as e:
            return f'CLICK FAIL: {str(e)[:40]}'
    return "NOOP"


# ═══════════════════════════════════════════════════════════════
#  Domain + Completion (unchanged from v1.1)
# ═══════════════════════════════════════════════════════════════
def detect_domain(url):
    u = url.lower()
    for pat, dom in [("localhost:9999", "forum"), ("localhost:8023", "gitlab"),
                     ("localhost:8001", "store"), ("localhost:8002", "booking"),
                     ("wikipedia", "wikipedia"), ("youtube", "youtube"),
                     ("github.com", "github"), ("google", "google")]:
        if pat in u: return dom
    return "other"

def check_completion(instruction, url, title, text, keyword, domain):
    u = url.lower()
    if domain == "google" and "/sorry/" in u:
        return True, "BLOCKED: Google captcha"
    if keyword:
        kw = keyword.lower()
        if kw in u: return True, f"Keyword '{keyword}' in URL"
        if kw in title.lower(): return True, f"Keyword '{keyword}' in title"
        if len(kw) >= 8 and kw in text.lower(): return True, f"Keyword '{keyword}' in text"
    if domain == "wikipedia" and "/wiki/" in u:
        slug = u.split("/wiki/")[-1].split("?")[0].split("#")[0]
        if slug and slug not in ("main_page", "special:search"):
            return True, f"Wiki article: /wiki/{slug}"
    if domain == "youtube" and "results?search_query=" in u:
        return True, "YouTube results loaded"
    if domain in ("store", "booking"):
        for m in ("vla_order_success", "vla_booking_success", "confirmation",
                  "order confirmed", "thank you for your order", "booking confirmed"):
            if m in text.lower(): return True, f"Marker: {m}"
    return False, ""

def get_text(page, n=500):
    try: return page.evaluate(f"()=>document.body?.innerText?.substring(0,{n})||''")
    except Exception: return ""


# ═══════════════════════════════════════════════════════════════
#  Banner + GitLab (unchanged)
# ═══════════════════════════════════════════════════════════════
def dismiss_banners(page):
    for s in ['button:text("Accept")', 'button:text("Accept all")',
              'button:text("Reject all")', 'button:text("I agree")',
              'button:text("Got it")', 'button:text("OK")',
              '#L2AGLb', '[aria-label="Close"]']:
        try:
            l = page.locator(s)
            if l.count() > 0: l.first.click(timeout=2000); time.sleep(0.3); return True
        except Exception: continue
    return False

def gitlab_login(page):
    if not GITLAB_USER or not GITLAB_PASS:
        print("    ⚠  GITLAB creds not set"); return
    try:
        page.goto("http://localhost:8023/users/sign_in", wait_until="domcontentloaded", timeout=10000); time.sleep(1)
        cl, ty = extract_elements(page)
        for e in ty:
            lb = e["label"].lower(); sel = f'[data-vla-id="{e["vla_id"]}"]'
            if any(k in lb for k in ("username", "email", "login")):
                h = page.query_selector(sel)
                if h: h.fill(GITLAB_USER); time.sleep(0.2)
            elif "password" in lb:
                h = page.query_selector(sel)
                if h: h.fill(GITLAB_PASS); time.sleep(0.2)
        for e in cl:
            if "sign in" in e["label"].lower() and "register" not in e["label"].lower():
                h = page.query_selector(f'[data-vla-id="{e["vla_id"]}"]')
                if h: h.click(); time.sleep(1.5); break
        print("    ✅ GitLab login attempted")
    except Exception as ex:
        print(f"    ⚠  GitLab login error: {str(ex)[:50]}")


# ═══════════════════════════════════════════════════════════════
#  Is this a submit-type button?
# ═══════════════════════════════════════════════════════════════
SUBMIT_KEYWORDS = {"submit", "confirm", "place order", "book", "checkout",
                   "complete", "finish", "pay", "next step", "proceed", "send"}

def is_submit_button(element):
    label = (element.get("label") or "").lower()
    return any(kw in label for kw in SUBMIT_KEYWORDS)


# ═══════════════════════════════════════════════════════════════
#  Run Single Scenario
# ═══════════════════════════════════════════════════════════════
def run_scenario(page, name, instruction, start_url, keyword,
                 max_steps, run_dir, visual=False):
    domain = detect_domain(start_url)
    print(f"\n{'━' * 72}")
    print(f"  📋 {name}")
    print(f"  Goal: {instruction}")
    print(f"  URL:  {start_url}  │  Domain: {domain}  │  Keyword: {keyword or '(none)'}")
    print(f"{'━' * 72}")

    ss_dir = os.path.join(run_dir, "screenshots")
    os.makedirs(ss_dir, exist_ok=True)

    trace = []
    result = {"name": name, "instruction": instruction, "start_url": start_url,
              "domain": domain, "keyword": keyword,
              "steps_taken": 0, "final_url": "", "success": False, "reason": "",
              "avg_adherence": 0.0}

    try:
        page.goto(start_url, wait_until="domcontentloaded", timeout=15000)
        time.sleep(2.0)
    except Exception as e:
        result["reason"] = f"Nav failed: {str(e)[:50]}"
        print(f"  ❌ {result['reason']}"); return result

    dismiss_banners(page)
    if domain == "gitlab" and GITLAB_USER:
        gitlab_login(page)
        if start_url != "http://localhost:8023/users/sign_in":
            try: page.goto(start_url, wait_until="domcontentloaded", timeout=10000); time.sleep(1)
            except Exception: pass

    action_history = []
    last_plan = ""
    url_history = []
    recently_clicked = set()
    last_url = ""
    adherence_scores = []

    for step in range(1, max_steps + 1):
        cur_url = page.url
        url_history.append(cur_url)
        title = ""
        try: title = page.title()
        except Exception: pass
        text_snip = get_text(page)

        if cur_url != last_url and last_url:
            recently_clicked.clear()

        # Completion
        done, reason = check_completion(instruction, cur_url, title, text_snip, keyword, domain)
        if done:
            try: page.screenshot(path=os.path.join(ss_dir, f"step_{step:02d}_done.png"))
            except Exception: pass
            result.update(steps_taken=step-1, final_url=cur_url,
                          success=("BLOCKED" not in reason), reason=reason)
            if adherence_scores:
                result["avg_adherence"] = round(sum(adherence_scores)/len(adherence_scores), 2)
            print(f"\n  {'🚫' if 'BLOCKED' in reason else '🎯'} {reason}")
            print(f"  Steps: {step-1}  │  URL: {cur_url[:65]}")
            break

        # Loop detection
        if len(url_history) >= SAME_URL_LIMIT:
            if len(set(url_history[-SAME_URL_LIMIT:])) == 1:
                result.update(steps_taken=step, final_url=cur_url,
                              reason=f"Loop: same URL >{SAME_URL_LIMIT}x")
                if adherence_scores:
                    result["avg_adherence"] = round(sum(adherence_scores)/len(adherence_scores), 2)
                print(f"\n  ⚠️  URL loop — stopping"); break

        # Screenshot
        try: page.screenshot(path=os.path.join(ss_dir, f"step_{step:02d}.png"))
        except Exception: pass

        # Extract
        clickable, typeable = extract_elements(page)
        if not clickable and not typeable:
            page.keyboard.press("PageDown"); time.sleep(0.5)
            clickable, typeable = extract_elements(page)
        if not clickable and not typeable:
            dismiss_banners(page); time.sleep(0.3)
            clickable, typeable = extract_elements(page)
        if not clickable and not typeable:
            result.update(steps_taken=step, final_url=cur_url, reason="No elements")
            print(f"  Step {step:>2} │ No elements — stopping"); break

        # Check empty form fields (for submit bias)
        empty_fields = get_empty_fields(page)

        # Build prompt
        prompt = build_prompt(instruction, cur_url, clickable, typeable,
                              action_history, last_plan, empty_fields,
                              recently_clicked)
        t0 = time.time()
        raw = llm_query(prompt)
        lat = time.time() - t0

        plan, action = parse_response(raw, clickable, typeable)
        last_plan = plan

        if action["type"] == "STOP":
            result.update(steps_taken=step, final_url=cur_url, reason="LLM STOP")
            d2, r2 = check_completion(instruction, cur_url, title, text_snip, keyword, domain)
            if d2: result.update(success=True, reason=r2)
            if adherence_scores:
                result["avg_adherence"] = round(sum(adherence_scores)/len(adherence_scores), 2)
            print(f"  Step {step:>2} │ STOP (LLM)"); break

        # Submit guard: if clicking a submit button but fields are empty, redirect to filling
        if (action["type"] == "CLICK" and is_submit_button(action.get("element", {}))
                and empty_fields):
            # Find an empty field to fill instead
            for e in typeable:
                e_name = (e.get("name") or e.get("label") or "").lower()
                for ef in empty_fields:
                    if ef.lower() in e_name or e_name in ef.lower():
                        # Redirect to typing this field
                        action = {"type": "TYPE", "id": str(e["vla_id"]),
                                  "text": f"[FILL {ef}]", "element": e,
                                  "submit_guard": True}
                        break
                if action.get("submit_guard"):
                    break

        # Action memory redirect
        if action["type"] == "CLICK" and action.get("id") in recently_clicked:
            for e in clickable:
                eid = str(e["vla_id"])
                if eid not in recently_clicked:
                    action = {"type": "CLICK", "id": eid, "element": e, "retry": True}
                    break
            else:
                recently_clicked.clear()

        last_url = cur_url

        # Execute
        action_desc = execute(page, action)
        action_history.append(action_desc)
        if action["type"] == "CLICK":
            recently_clicked.add(action.get("id", ""))

        # Adherence
        adh = compute_adherence(plan, action_desc, cur_url)
        adherence_scores.append(adh)

        fb = " ⟵fb" if action.get("fallback") else ""
        rt = " ↻rt" if action.get("retry") else ""
        sg = " 🛡guard" if action.get("submit_guard") else ""

        step_data = {
            "step": step, "url": cur_url,
            "action_type": action["type"], "action_desc": action_desc,
            "element_label": action.get("element", {}).get("label", ""),
            "element_vla_id": action.get("id", ""),
            "plan": plan, "adherence": adh,
            "llm_raw": raw[:200], "llm_latency": round(lat, 2),
            "fallback": bool(action.get("fallback")),
            "retry": bool(action.get("retry")),
            "submit_guard": bool(action.get("submit_guard")),
            "empty_fields": empty_fields[:5],
            "n_clickable": len(clickable), "n_typeable": len(typeable),
        }
        trace.append(step_data)

        plan_short = plan.split("\n")[0][:40] if plan else "(no plan)"
        print(f"  Step {step:>2} │ {action_desc[:48]:<48} │ "
              f"{lat:.1f}s │ adh={adh}{fb}{rt}{sg}")
        if visual and plan:
            for line in plan.split("\n")[:3]:
                print(f"         │ 📝 {line.strip()}")

        result["steps_taken"] = step
        result["final_url"] = page.url

        if visual:
            time.sleep(0.8)
        else:
            time.sleep(0.2)

    else:
        cur_url = page.url
        title = ""
        try: title = page.title()
        except Exception: pass
        text_snip = get_text(page)
        d, r = check_completion(instruction, cur_url, title, text_snip, keyword, domain)
        result.update(final_url=cur_url, steps_taken=max_steps,
                      success=d, reason=r or "Max steps")

    if adherence_scores:
        result["avg_adherence"] = round(sum(adherence_scores)/len(adherence_scores), 2)

    safe_name = re.sub(r'[^a-zA-Z0-9_]', '_', name)[:40]
    trace_path = os.path.join(run_dir, f"trace_{safe_name}.json")
    with open(trace_path, "w") as f:
        json.dump({"scenario": result, "steps": trace}, f, indent=2)

    st = "✅" if result["success"] else "❌"
    print(f"\n  {st}  {result['reason']}")
    print(f"  Steps: {result['steps_taken']}  │  Adherence: {result['avg_adherence']}")
    print(f"  Final: {result['final_url'][:70]}")
    return result


# ═══════════════════════════════════════════════════════════════
#  Main
# ═══════════════════════════════════════════════════════════════
def main():
    ap = argparse.ArgumentParser(description="Unified VLA Agent v1.2")
    ap.add_argument("--scenarios", type=str, default=None)
    ap.add_argument("--builtin", action="store_true")
    ap.add_argument("--headless", type=str, default="false")
    ap.add_argument("--max-steps", type=int, default=MAX_STEPS_DEFAULT)
    ap.add_argument("--visual", action="store_true",
                    help="Visual debug: show plans, 0.8s delay per step")
    args = ap.parse_args()

    headless = args.headless.lower() in ("true", "1", "yes")

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("❌ playwright not installed"); sys.exit(1)

    scenarios = []
    if args.scenarios:
        with open(args.scenarios) as f: scenarios = json.load(f)
        mode = f"Scenarios: {args.scenarios}"
    elif args.builtin:
        scenarios = BUILTIN_SCENARIOS; mode = "Built-in"
    else:
        mode = "Interactive"

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = os.path.join(SCRIPT_DIR, "runs", ts)
    os.makedirs(run_dir, exist_ok=True)

    print()
    print("══════════════════════════════════════════════════════════")
    print("  UNIFIED VLA AGENT v1.2 — PLAN→ACTION")
    print("══════════════════════════════════════════════════════════")
    print(f"  Model:    {MODEL_NAME} (temp={TEMPERATURE})")
    print(f"  API:      /api/chat (think=false, predict={NUM_PREDICT})")
    print(f"  Mode:     {mode}")
    print(f"  Visual:   {args.visual}")
    print(f"  Run dir:  {run_dir}")
    print("══════════════════════════════════════════════════════════")

    results = []

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=headless)
        ctx = browser.new_context(viewport={"width": 1280, "height": 720},
                                  locale="en-US")
        try:
            if scenarios:
                for i, sc in enumerate(scenarios, 1):
                    page = ctx.new_page()
                    try:
                        r = run_scenario(page, sc.get("name", f"S{i}"),
                            sc["instruction"], sc["start_url"],
                            sc.get("completion_keyword"),
                            sc.get("max_steps", args.max_steps),
                            run_dir, visual=args.visual)
                        results.append(r)
                    finally:
                        try: page.close()
                        except Exception: pass
                    if i < len(scenarios): time.sleep(2)
            else:
                idx = 0
                while True:
                    print()
                    try: instr = input("Instruction (or 'quit'): ").strip()
                    except (EOFError, KeyboardInterrupt): print("\n  Bye!"); break
                    if not instr or instr.lower() in ("quit", "exit", "q"): break
                    try: url = input("Start URL [https://www.google.com]: ").strip() or "https://www.google.com"
                    except (EOFError, KeyboardInterrupt): break
                    try: kw = input("Completion keyword (optional): ").strip()
                    except (EOFError, KeyboardInterrupt): break
                    try: ms = int(input(f"Max steps [{args.max_steps}]: ").strip() or args.max_steps)
                    except (ValueError, EOFError, KeyboardInterrupt): ms = args.max_steps
                    idx += 1
                    page = ctx.new_page()
                    try:
                        r = run_scenario(page, f"Interactive-{idx}", instr, url,
                                         kw or None, ms, run_dir, visual=args.visual)
                        results.append(r)
                    finally:
                        try: page.close()
                        except Exception: pass
        finally:
            try: ctx.close(); browser.close()
            except Exception: pass

    # Summary
    if results:
        print()
        print("══════════════════════════════════════════════════════════")
        print("  RESULTS — v1.2 PLAN→ACTION")
        print("══════════════════════════════════════════════════════════")
        print(f"  {'#':>2}  {'OK':>3}  {'Stp':>4}  {'Adh':>5}  {'Dom':<9}  "
              f"{'Name':<30}  Reason")
        print(f"  {'─' * 95}")
        for i, r in enumerate(results, 1):
            s = "✅" if r["success"] else "❌"
            print(f"  {i:>2}  {s:>3}  {r['steps_taken']:>4}  "
                  f"{r.get('avg_adherence',0):>5.2f}  {r['domain']:<9}  "
                  f"{r['name'][:30]:<30}  {r['reason'][:35]}")
        tot = len(results)
        ok = sum(1 for r in results if r["success"])
        avg_adh = sum(r.get("avg_adherence", 0) for r in results) / max(tot, 1)
        print(f"\n  Total: {tot}  │  Success: {ok}/{tot} ({ok/max(tot,1)*100:.0f}%)  │  "
              f"Avg adherence: {avg_adh:.2f}")

        sp = os.path.join(run_dir, "summary.json")
        with open(sp, "w") as f: json.dump(results, f, indent=2)
        print(f"\n  📁 {run_dir}")

    print()
    print("══════════════════════════════════════════════════════════")
    print("  UNIFIED v1.2 LOCKED. READY FOR NEXT ITERATION.")
    print("══════════════════════════════════════════════════════════")

if __name__ == "__main__":
    main()
