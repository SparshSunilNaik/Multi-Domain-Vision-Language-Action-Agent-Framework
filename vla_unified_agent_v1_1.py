#!/usr/bin/env python3
"""
Unified VLA Agent v1.1 — Patched Multi-Domain Web Navigator.

Fixes from v1.0 validation:
  FIX 1: DOM extraction includes radio, checkbox, select, option
  FIX 2: TYPE only auto-presses Enter for search-type inputs
  FIX 3: Same-URL loop threshold raised from 6 → 12
  FIX 4: Minimal action memory to prevent blind repetition

Architecture preserved: Ollama qwen3:8b, /api/chat, think:false,
data-vla-id injection, headless=False, no safety gating.

Usage:
    python vla_unified_agent_v1_1.py                          # Interactive mode
    python vla_unified_agent_v1_1.py --scenarios file.json    # Scenario-file mode
    python vla_unified_agent_v1_1.py --builtin                # Built-in test scenarios
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
OLLAMA_URL    = "http://localhost:11434/api/chat"
MODEL_NAME    = "qwen3:8b"
TEMPERATURE   = 0.7
NUM_PREDICT   = 80
MAX_STEPS_DEFAULT = 20
MAX_CLICKABLE = 20       # Increased to accommodate radio/checkbox/select
MAX_TYPEABLE  = 5
MAX_TEXT_LEN  = 80
SAME_URL_LIMIT = 12      # FIX 3: raised from 6 → 12

GITLAB_USER = os.environ.get("GITLAB_USER", "")
GITLAB_PASS = os.environ.get("GITLAB_PASS", "")

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# ═══════════════════════════════════════════════════════════════
#  Built-in Test Scenarios
# ═══════════════════════════════════════════════════════════════
BUILTIN_SCENARIOS = [
    {
        "name": "Wikipedia — Alan Turing",
        "instruction": "Search for Alan Turing on Wikipedia.",
        "start_url": "https://en.wikipedia.org",
        "completion_keyword": "/wiki/Alan_Turing",
        "max_steps": 10,
    },
    {
        "name": "YouTube — ML Basics",
        "instruction": "Search for 'machine learning basics'.",
        "start_url": "https://www.youtube.com",
        "completion_keyword": "results",
        "max_steps": 10,
    },
    {
        "name": "GitHub — Open",
        "instruction": "Go to GitHub homepage.",
        "start_url": "https://github.com",
        "completion_keyword": "github.com",
        "max_steps": 5,
    },
    {
        "name": "Google — OpenAI (captcha test)",
        "instruction": "Search for 'OpenAI' on Google.",
        "start_url": "https://www.google.com",
        "completion_keyword": "search?q=",
        "max_steps": 10,
    },
]

# ═══════════════════════════════════════════════════════════════
#  JS DOM Extraction — FIX 1: radio/checkbox/select/option added
# ═══════════════════════════════════════════════════════════════
EXTRACT_JS = """
() => {
    const results = [];
    const seen = new Set();
    let counter = 0;

    function isVisible(el) {
        // Radio/checkbox are often tiny; check parent visibility instead
        const check = (el.tagName === 'INPUT' &&
            (el.type === 'radio' || el.type === 'checkbox'))
            ? (el.parentElement || el) : el;
        if (!check.offsetParent && check.tagName !== 'BODY' && check.tagName !== 'HTML') return false;
        const r = check.getBoundingClientRect();
        if (r.width === 0 || r.height === 0) {
            // Radio/checkbox can be 0-sized but still functional if label is visible
            if (el.tagName === 'INPUT' && (el.type === 'radio' || el.type === 'checkbox')) {
                const label = document.querySelector('label[for="' + el.id + '"]');
                if (label) {
                    const lr = label.getBoundingClientRect();
                    if (lr.width > 0 && lr.height > 0) return true;
                }
                // Check parent
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
        // For radio/checkbox, try associated label first
        if (el.tagName === 'INPUT' && (el.type === 'radio' || el.type === 'checkbox')) {
            if (el.id) {
                const lbl = document.querySelector('label[for="' + el.id + '"]');
                if (lbl) return lbl.textContent.trim().substring(0, 80);
            }
            // Check parent label
            const parentLabel = el.closest('label');
            if (parentLabel) return parentLabel.textContent.trim().substring(0, 80);
            // Check next sibling text
            if (el.nextSibling && el.nextSibling.textContent) {
                const t = el.nextSibling.textContent.trim().substring(0, 80);
                if (t) return t;
            }
        }
        // For select
        if (el.tagName === 'SELECT') {
            const lbl = el.getAttribute('aria-label') ||
                el.getAttribute('name') || el.getAttribute('id') || '';
            const selected = el.options && el.selectedIndex >= 0
                ? el.options[el.selectedIndex].text : '';
            return (lbl ? lbl + (selected ? ' [' + selected + ']' : '') : selected)
                .trim().substring(0, 80) || 'dropdown';
        }
        // For option
        if (el.tagName === 'OPTION') {
            return el.textContent.trim().substring(0, 80);
        }
        return (
            el.getAttribute('aria-label') ||
            el.getAttribute('title') ||
            el.getAttribute('placeholder') ||
            el.getAttribute('alt') ||
            el.textContent.trim().substring(0, 80) ||
            el.getAttribute('name') ||
            el.getAttribute('id') ||
            ''
        ).trim().replace(/\\s+/g, ' ').substring(0, 80);
    }

    function tag(el) {
        counter++;
        el.setAttribute('data-vla-id', String(counter));
        return counter;
    }

    // ── Clickable: buttons, links, radio, checkbox ──
    document.querySelectorAll(
        'a[href], button, [role="button"], [role="link"], [role="menuitem"], ' +
        '[role="tab"], [role="option"], [onclick], summary, [role="treeitem"], ' +
        'input[type="radio"], input[type="checkbox"]'
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
        if (!role) {
            if (el.tagName === 'A') role = 'link';
            else if (inputType === 'radio') role = 'radio';
            else if (inputType === 'checkbox') role = 'checkbox';
            else role = 'button';
        }
        results.push({
            vla_id: vid, kind: 'clickable',
            tag: el.tagName.toLowerCase(),
            role: role,
            label: label,
            input_type: inputType,
            name: el.getAttribute('name') || null,
            el_id: el.getAttribute('id') || null,
        });
    });

    // ── Select elements (shown as clickable with options) ──
    document.querySelectorAll('select').forEach(el => {
        if (!isVisible(el)) return;
        const label = getLabel(el);
        const vid = tag(el);
        const options = [];
        if (el.options) {
            for (let i = 0; i < el.options.length && i < 10; i++) {
                options.push(el.options[i].text.trim().substring(0, 40));
            }
        }
        results.push({
            vla_id: vid, kind: 'clickable',
            tag: 'select',
            role: 'listbox',
            label: label + (options.length ? ' (' + options.join(', ') + ')' : ''),
            input_type: 'select',
            name: el.getAttribute('name') || null,
            el_id: el.getAttribute('id') || null,
        });
    });

    // ── Typeable: text/search/email/password/url/tel/number inputs ──
    document.querySelectorAll(
        'input[type="text"], input[type="search"], input[type="email"], ' +
        'input[type="password"], input[type="url"], input[type="tel"], ' +
        'input[type="number"], input[type="date"], input:not([type]), textarea, ' +
        '[contenteditable="true"], [role="textbox"], [role="searchbox"], [role="combobox"]'
    ).forEach(el => {
        if (!isVisible(el)) return;
        // Skip radio/checkbox that might match input:not([type])
        if (el.tagName === 'INPUT') {
            const t = (el.getAttribute('type') || '').toLowerCase();
            if (t === 'radio' || t === 'checkbox' || t === 'hidden' || t === 'submit' || t === 'button') return;
        }
        const label = getLabel(el) || el.getAttribute('type') || 'text input';
        const key = 't:' + label.toLowerCase().substring(0, 40);
        if (seen.has(key)) return;
        seen.add(key);
        const vid = tag(el);
        results.push({
            vla_id: vid, kind: 'typeable',
            tag: el.tagName.toLowerCase(),
            role: el.getAttribute('role') || 'textbox',
            label: label,
            input_type: el.getAttribute('type') || null,
            name: el.getAttribute('name') || null,
            el_id: el.getAttribute('id') || null,
            placeholder: el.getAttribute('placeholder') || null,
        });
    });

    return results;
}
"""

# ═══════════════════════════════════════════════════════════════
#  Ollama /api/chat  (think: false)
# ═══════════════════════════════════════════════════════════════
def llm_query(prompt, max_tokens=NUM_PREDICT):
    payload = json.dumps({
        "model": MODEL_NAME,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        "think": False,
        "options": {"temperature": TEMPERATURE, "num_predict": max_tokens},
    }).encode()
    req = urllib.request.Request(
        OLLAMA_URL, data=payload,
        headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=90) as r:
            body = json.loads(r.read().decode())
            raw = body.get("message", {}).get("content", "").strip()
            raw = re.sub(r'<think>.*?</think>', '', raw, flags=re.DOTALL).strip()
            return raw
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
    clickable = [e for e in raw if e["kind"] == "clickable"][:MAX_CLICKABLE]
    typeable  = [e for e in raw if e["kind"] == "typeable"][:MAX_TYPEABLE]
    return clickable, typeable


# ═══════════════════════════════════════════════════════════════
#  Prompt Builder
# ═══════════════════════════════════════════════════════════════
def build_prompt(instruction, url, clickable, typeable, last_action,
                 skip_ids=None):
    cl_lines = []
    for e in clickable:
        marker = ""
        if skip_ids and str(e["vla_id"]) in skip_ids:
            marker = " (already clicked, try different)"
        cl_lines.append(
            f'  [{e["vla_id"]}] {e["role"]} "{e["label"]}"{marker}')
    cl = "\n".join(cl_lines) or "  (none)"

    tl = "\n".join(f'  [{e["vla_id"]}] {e["role"]} "{e["label"]}"'
                   for e in typeable) or "  (none)"
    prev = f"\nLast action: {last_action}" if last_action else ""
    return f"""You are a web navigation agent.

Instruction: "{instruction}"

URL: {url}{prev}

Clickable:
{cl}

Typeable:
{tl}

Respond with exactly ONE line:
CLICK <id>
TYPE <id> "<text>"
STOP

Output only the action line, nothing else."""


# ═══════════════════════════════════════════════════════════════
#  Strict Action Parser
# ═══════════════════════════════════════════════════════════════
def parse_action(response, clickable, typeable):
    all_el = {str(e["vla_id"]): e for e in clickable + typeable}

    # STOP
    if re.search(r'\bSTOP\b', response, re.IGNORECASE):
        return {"type": "STOP"}

    # TYPE <id> "text"
    for pat in [r'TYPE\s+(\S+)\s+"([^"]+)"',
                r"TYPE\s+(\S+)\s+'([^']+)'",
                r'TYPE\s+(\S+)\s+(.+)']:
        m = re.search(pat, response, re.IGNORECASE)
        if m:
            eid = m.group(1).strip("[]\"'")
            txt = m.group(2).replace("\n", " ").strip()[:MAX_TEXT_LEN]
            if eid in all_el and txt:
                return {"type": "TYPE", "id": eid, "text": txt,
                        "element": all_el[eid]}
            break

    # CLICK <id>
    m = re.search(r'CLICK\s+(\S+)', response, re.IGNORECASE)
    if m:
        eid = m.group(1).strip("[]\"'")
        if eid in all_el:
            return {"type": "CLICK", "id": eid, "element": all_el[eid]}

    # Deterministic fallback
    for e in typeable:
        lbl = e["label"].lower()
        if any(k in lbl for k in ("search", "query", "find")):
            return {"type": "CLICK", "id": str(e["vla_id"]),
                    "element": e, "fallback": True}
    if clickable:
        return {"type": "CLICK", "id": str(clickable[0]["vla_id"]),
                "element": clickable[0], "fallback": True}
    if typeable:
        return {"type": "CLICK", "id": str(typeable[0]["vla_id"]),
                "element": typeable[0], "fallback": True}
    return {"type": "STOP"}


# ═══════════════════════════════════════════════════════════════
#  FIX 2: Helper — should we press Enter after typing?
# ═══════════════════════════════════════════════════════════════
def _should_press_enter(element):
    """Only press Enter for search-type inputs, not generic form fields."""
    itype = (element.get("input_type") or "").lower()
    if itype == "search":
        return True
    placeholder = (element.get("placeholder") or "").lower()
    if "search" in placeholder:
        return True
    name = (element.get("name") or "").lower()
    el_id = (element.get("el_id") or "").lower()
    label = (element.get("label") or "").lower()
    if name == "q" or el_id == "q":
        return True
    if "search" in name or "search" in el_id or "search" in label:
        return True
    return False


# ═══════════════════════════════════════════════════════════════
#  Action Executor — FIX 2: conditional Enter
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
        press_enter = _should_press_enter(el)
        try:
            h = page.query_selector(sel)
            if h:
                h.click(); time.sleep(0.1)
                h.fill(text); time.sleep(0.1)
                if press_enter:
                    h.press("Enter"); time.sleep(0.8)
                else:
                    time.sleep(0.3)
                enter_note = " ⏎" if press_enter else ""
                return f'TYPE [{vid}] "{label}" ← "{text}"{enter_note}'
            page.keyboard.type(text, delay=25)
            if press_enter:
                page.keyboard.press("Enter"); time.sleep(0.5)
            return f'TYPE (keyboard) ← "{text}"'
        except Exception as e:
            try:
                page.keyboard.type(text, delay=25)
                if press_enter:
                    page.keyboard.press("Enter"); time.sleep(0.5)
                return f'TYPE (kb-fallback) ← "{text}"'
            except Exception:
                return f'TYPE FAILED: {str(e)[:40]}'

    if action["type"] == "CLICK":
        try:
            h = page.query_selector(sel)
            if h:
                h.scroll_into_view_if_needed(timeout=3000)
                time.sleep(0.1)
                h.click(timeout=5000)
                time.sleep(0.6)
                return f'CLICK [{vid}] "{label}"'
            loc = page.get_by_text(label, exact=False)
            if loc.count() > 0:
                loc.first.click(timeout=5000)
                time.sleep(0.5)
                return f'CLICK (text) "{label}"'
            return f'CLICK SKIP: "{label}" not found'
        except Exception as e:
            return f'CLICK FAILED: {str(e)[:40]}'

    return "NOOP"


# ═══════════════════════════════════════════════════════════════
#  Domain Detection
# ═══════════════════════════════════════════════════════════════
def detect_domain(url):
    u = url.lower()
    if "localhost:9999" in u:       return "forum"
    if "localhost:8023" in u:       return "gitlab"
    if "localhost:8001" in u:       return "store"
    if "localhost:8002" in u:       return "booking"
    if "wikipedia" in u:            return "wikipedia"
    if "youtube" in u:              return "youtube"
    if "github.com" in u:           return "github"
    if "google" in u:               return "google"
    return "other"


# ═══════════════════════════════════════════════════════════════
#  Completion Detection  (multi-signal)
# ═══════════════════════════════════════════════════════════════
def check_completion(instruction, url, page_title, page_text_snippet,
                     keyword, domain):
    u = url.lower()

    if domain == "google" and "/sorry/" in u:
        return True, "BLOCKED: Google captcha (/sorry/). Try Bing or DuckDuckGo."

    if keyword:
        kw = keyword.lower()
        if kw in u:
            return True, f"Keyword '{keyword}' found in URL"
        if kw in page_title.lower():
            return True, f"Keyword '{keyword}' found in page title"
        if len(kw) >= 8 and kw in page_text_snippet.lower():
            return True, f"Keyword '{keyword}' found in page text"

    if domain == "wikipedia" and "/wiki/" in u:
        slug = u.split("/wiki/")[-1].split("?")[0].split("#")[0]
        if slug and slug != "main_page" and slug != "special:search":
            return True, f"Wikipedia article loaded: /wiki/{slug}"

    if domain == "youtube" and "results?search_query=" in u:
        return True, "YouTube search results loaded"

    if domain in ("store", "booking"):
        for marker in ("vla_order_success", "vla_booking_success",
                        "confirmation", "order confirmed",
                        "thank you for your order", "booking confirmed"):
            if marker in page_text_snippet.lower():
                return True, f"Success marker found: {marker}"

    return False, ""


def get_page_text_snippet(page, length=500):
    try:
        return page.evaluate(
            f"() => document.body?.innerText?.substring(0, {length}) || ''"
        )
    except Exception:
        return ""


# ═══════════════════════════════════════════════════════════════
#  Banner Dismissal
# ═══════════════════════════════════════════════════════════════
def dismiss_banners(page):
    for sel in ['button:text("Accept")', 'button:text("Accept all")',
                'button:text("Reject all")', 'button:text("I agree")',
                'button:text("Got it")', 'button:text("OK")',
                '#L2AGLb', '[aria-label="Close"]']:
        try:
            loc = page.locator(sel)
            if loc.count() > 0:
                loc.first.click(timeout=2000); time.sleep(0.3)
                return True
        except Exception:
            continue
    return False


# ═══════════════════════════════════════════════════════════════
#  GitLab Login  (uses env vars, not hardcoded)
# ═══════════════════════════════════════════════════════════════
def gitlab_login(page):
    if not GITLAB_USER or not GITLAB_PASS:
        print("    ⚠  GITLAB_USER / GITLAB_PASS env vars not set — skipping login")
        return
    try:
        page.goto("http://localhost:8023/users/sign_in",
                   wait_until="domcontentloaded", timeout=10000)
        time.sleep(1)
        clickable, typeable = extract_elements(page)
        for e in typeable:
            lbl = e["label"].lower()
            sel = f'[data-vla-id="{e["vla_id"]}"]'
            if "username" in lbl or "email" in lbl or "login" in lbl:
                h = page.query_selector(sel)
                if h: h.fill(GITLAB_USER); time.sleep(0.2)
            elif "password" in lbl:
                h = page.query_selector(sel)
                if h: h.fill(GITLAB_PASS); time.sleep(0.2)
        for e in clickable:
            if "sign in" in e["label"].lower() and "register" not in e["label"].lower():
                h = page.query_selector(f'[data-vla-id="{e["vla_id"]}"]')
                if h: h.click(); time.sleep(1.5); break
        print("    ✅ GitLab login attempted")
    except Exception as ex:
        print(f"    ⚠  GitLab login error: {str(ex)[:50]}")


# ═══════════════════════════════════════════════════════════════
#  Run Single Scenario — FIX 4: action memory
# ═══════════════════════════════════════════════════════════════
def run_scenario(page, name, instruction, start_url, keyword,
                 max_steps, run_dir):
    domain = detect_domain(start_url)

    print(f"\n{'━' * 72}")
    print(f"  📋 {name}")
    print(f"  Instruction: {instruction}")
    print(f"  URL:         {start_url}")
    print(f"  Domain:      {domain}")
    print(f"  Keyword:     {keyword or '(none)'}")
    print(f"  Max steps:   {max_steps}")
    print(f"{'━' * 72}")

    ss_dir = os.path.join(run_dir, "screenshots")
    os.makedirs(ss_dir, exist_ok=True)

    trace = []
    result = {
        "name": name, "instruction": instruction, "start_url": start_url,
        "domain": domain, "keyword": keyword,
        "steps_taken": 0, "final_url": "", "success": False, "reason": "",
    }

    try:
        page.goto(start_url, wait_until="domcontentloaded", timeout=15000)
        time.sleep(2.0)
    except Exception as e:
        result["reason"] = f"Navigation failed: {str(e)[:50]}"
        print(f"  ❌ {result['reason']}")
        return result

    dismiss_banners(page)

    if domain == "gitlab" and GITLAB_USER:
        gitlab_login(page)
        if start_url != "http://localhost:8023/users/sign_in":
            try:
                page.goto(start_url, wait_until="domcontentloaded",
                          timeout=10000)
                time.sleep(1)
            except Exception:
                pass

    last_action = None
    url_history = []

    # FIX 4: Minimal action memory
    recently_clicked = set()   # set of vla_id strings that were clicked
    last_url_before_action = ""

    for step in range(1, max_steps + 1):
        cur_url = page.url
        url_history.append(cur_url)
        title = ""
        try: title = page.title()
        except Exception: pass
        text_snip = get_page_text_snippet(page)

        # FIX 4: Clear memory if URL changed
        if cur_url != last_url_before_action and last_url_before_action:
            recently_clicked.clear()

        # ── Completion check ──
        done, reason = check_completion(
            instruction, cur_url, title, text_snip, keyword, domain)
        if done:
            try: page.screenshot(
                path=os.path.join(ss_dir, f"step_{step:02d}_done.png"))
            except Exception: pass
            result.update(steps_taken=step-1, final_url=cur_url,
                          success=("BLOCKED" not in reason), reason=reason)
            print(f"\n  {'🚫' if 'BLOCKED' in reason else '🎯'} {reason}")
            print(f"  Steps: {step-1}  |  URL: {cur_url[:70]}")
            if "BLOCKED" in reason:
                print(f"  💡 Suggestion: use Bing (bing.com) or DuckDuckGo (duckduckgo.com)")
            break

        # ── Same-URL loop detection (FIX 3: threshold 12) ──
        if len(url_history) >= SAME_URL_LIMIT:
            recent = url_history[-SAME_URL_LIMIT:]
            if len(set(recent)) == 1:
                result.update(steps_taken=step, final_url=cur_url,
                              reason=f"Stopped: same URL repeated >{SAME_URL_LIMIT} times")
                print(f"\n  ⚠️  Same URL repeated {SAME_URL_LIMIT}x — stopping")
                break

        # Screenshots
        try: page.screenshot(
            path=os.path.join(ss_dir, f"step_{step:02d}.png"))
        except Exception: pass

        # ── Extract elements ──
        clickable, typeable = extract_elements(page)
        if not clickable and not typeable:
            page.keyboard.press("PageDown"); time.sleep(0.5)
            clickable, typeable = extract_elements(page)
        if not clickable and not typeable:
            dismiss_banners(page); time.sleep(0.3)
            clickable, typeable = extract_elements(page)
        if not clickable and not typeable:
            result.update(steps_taken=step, final_url=cur_url,
                          reason="No actionable elements found")
            print(f"  Step {step:>2} │ No elements — stopping")
            break

        # ── LLM action (FIX 4: pass skip hints) ──
        prompt = build_prompt(instruction, cur_url, clickable, typeable,
                              last_action, skip_ids=recently_clicked)
        t0 = time.time()
        raw = llm_query(prompt)
        lat = time.time() - t0

        action = parse_action(raw, clickable, typeable)

        if action["type"] == "STOP":
            result.update(steps_taken=step, final_url=cur_url,
                          reason="LLM output STOP")
            d, r = check_completion(instruction, cur_url, title,
                                     text_snip, keyword, domain)
            if d: result.update(success=True, reason=r)
            print(f"  Step {step:>2} │ STOP  (LLM)")
            break

        # FIX 4: If CLICK and already clicked same element on same URL, try next
        if action["type"] == "CLICK" and action.get("id") in recently_clicked:
            # Find an alternative action
            alt_found = False
            for e in clickable:
                eid = str(e["vla_id"])
                if eid not in recently_clicked:
                    action = {"type": "CLICK", "id": eid, "element": e,
                              "retry": True}
                    alt_found = True
                    break
            if not alt_found:
                # All clicked already; clear memory and let it try again
                recently_clicked.clear()

        # Record URL before action for FIX 4 comparison
        last_url_before_action = cur_url

        # ── Execute ──
        action_desc = execute(page, action)
        last_action = action_desc

        # FIX 4: Track clicked IDs
        if action["type"] == "CLICK":
            recently_clicked.add(action.get("id", ""))

        fb = " ⟵fallback" if action.get("fallback") else ""
        retry = " ↻retry" if action.get("retry") else ""

        elem_info = action.get("element", {})
        step_data = {
            "step": step, "url": cur_url,
            "action_type": action["type"],
            "action_desc": action_desc,
            "element_label": elem_info.get("label", ""),
            "element_vla_id": action.get("id", ""),
            "llm_raw": raw[:100], "llm_latency": round(lat, 2),
            "fallback": bool(action.get("fallback")),
            "retry": bool(action.get("retry")),
            "n_clickable": len(clickable), "n_typeable": len(typeable),
        }
        trace.append(step_data)

        print(f"  Step {step:>2} │ {action_desc[:55]:<55} │ "
              f"{lat:.1f}s{fb}{retry}")

        result["steps_taken"] = step
        result["final_url"] = page.url
        time.sleep(0.2)

    else:
        cur_url = page.url
        title = ""
        try: title = page.title()
        except Exception: pass
        text_snip = get_page_text_snippet(page)
        done, reason = check_completion(
            instruction, cur_url, title, text_snip, keyword, domain)
        result.update(final_url=cur_url, steps_taken=max_steps,
                      success=done, reason=reason or "Max steps reached")

    # Save trace JSON
    safe_name = re.sub(r'[^a-zA-Z0-9_]', '_', name)[:40]
    trace_path = os.path.join(run_dir, f"trace_{safe_name}.json")
    with open(trace_path, "w") as f:
        json.dump({"scenario": result, "steps": trace}, f, indent=2)

    status = "✅" if result["success"] else "❌"
    print(f"\n  {status}  {result['reason']}")
    print(f"  Steps: {result['steps_taken']}  |  "
          f"Final: {result['final_url'][:70]}")

    return result


# ═══════════════════════════════════════════════════════════════
#  Main
# ═══════════════════════════════════════════════════════════════
def main():
    ap = argparse.ArgumentParser(description="Unified VLA Agent v1.1")
    ap.add_argument("--scenarios", type=str, default=None,
                    help="Path to JSON scenarios file")
    ap.add_argument("--builtin", action="store_true",
                    help="Run built-in test scenarios")
    ap.add_argument("--headless", type=str, default="false",
                    help="Browser headless mode (default: false)")
    ap.add_argument("--max-steps", type=int, default=MAX_STEPS_DEFAULT,
                    help="Default max steps per scenario")
    args = ap.parse_args()

    headless = args.headless.lower() in ("true", "1", "yes")

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("❌ playwright not installed"); sys.exit(1)

    scenarios = []
    if args.scenarios:
        with open(args.scenarios) as f:
            scenarios = json.load(f)
        mode_label = f"Scenario file: {args.scenarios}"
    elif args.builtin:
        scenarios = BUILTIN_SCENARIOS
        mode_label = "Built-in test scenarios"
    else:
        mode_label = "Interactive"

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = os.path.join(SCRIPT_DIR, "runs", ts)
    os.makedirs(run_dir, exist_ok=True)

    print()
    print("══════════════════════════════════════════════════════════")
    print("  UNIFIED VLA AGENT v1.1 (patched)")
    print("══════════════════════════════════════════════════════════")
    print(f"  Model:     {MODEL_NAME} (temp={TEMPERATURE})")
    print(f"  API:       /api/chat (think=false)")
    print(f"  Headless:  {headless}")
    print(f"  Mode:      {mode_label}")
    print(f"  Run dir:   {run_dir}")
    print(f"  Fixes:     radio/checkbox/select extraction, conditional Enter,")
    print(f"             loop threshold {SAME_URL_LIMIT}, action memory")
    if GITLAB_USER:
        print(f"  GitLab:    user={GITLAB_USER}")
    else:
        print(f"  GitLab:    (no creds — set GITLAB_USER & GITLAB_PASS)")
    print("══════════════════════════════════════════════════════════")

    all_results = []

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=headless)
        ctx = browser.new_context(
            viewport={"width": 1280, "height": 720}, locale="en-US")

        try:
            if scenarios:
                for i, sc in enumerate(scenarios, 1):
                    page = ctx.new_page()
                    try:
                        r = run_scenario(
                            page,
                            sc.get("name", f"Scenario {i}"),
                            sc["instruction"],
                            sc["start_url"],
                            sc.get("completion_keyword"),
                            sc.get("max_steps", args.max_steps),
                            run_dir,
                        )
                        all_results.append(r)
                    finally:
                        try: page.close()
                        except Exception: pass
                    if i < len(scenarios):
                        time.sleep(2)
            else:
                idx = 0
                while True:
                    print()
                    try:
                        instr = input("Instruction (or 'quit'): ").strip()
                    except (EOFError, KeyboardInterrupt):
                        print("\n  Goodbye!"); break
                    if not instr or instr.lower() in ("quit", "exit", "q"):
                        break
                    try:
                        url = input("Start URL [https://www.google.com]: ").strip()
                    except (EOFError, KeyboardInterrupt):
                        print("\n  Goodbye!"); break
                    if not url: url = "https://www.google.com"
                    try:
                        kw = input("Completion keyword (optional): ").strip()
                    except (EOFError, KeyboardInterrupt):
                        print("\n  Goodbye!"); break
                    try:
                        ms = input(f"Max steps [{args.max_steps}]: ").strip()
                        ms = int(ms) if ms else args.max_steps
                    except (ValueError, EOFError, KeyboardInterrupt):
                        ms = args.max_steps

                    idx += 1
                    page = ctx.new_page()
                    try:
                        r = run_scenario(page, f"Interactive-{idx}",
                                         instr, url, kw or None, ms,
                                         run_dir)
                        all_results.append(r)
                    finally:
                        try: page.close()
                        except Exception: pass

        finally:
            try: ctx.close(); browser.close()
            except Exception: pass

    # ═══════════════════════════════════════════════════════════
    #  Final Summary
    # ═══════════════════════════════════════════════════════════
    if all_results:
        print()
        print("══════════════════════════════════════════════════════════")
        print("  RESULTS SUMMARY — v1.1")
        print("══════════════════════════════════════════════════════════")
        print(f"  {'#':>2}  {'OK':>3}  {'Steps':>5}  {'Domain':<10}  "
              f"{'Name':<30}  Reason")
        print(f"  {'─' * 95}")
        for i, r in enumerate(all_results, 1):
            st = "✅" if r["success"] else "❌"
            print(f"  {i:>2}  {st:>3}  {r['steps_taken']:>5}  "
                  f"{r['domain']:<10}  {r['name'][:30]:<30}  "
                  f"{r['reason'][:35]}")
        total = len(all_results)
        ok = sum(1 for r in all_results if r["success"])
        print(f"\n  Total: {total}  |  Success: {ok}/{total}  |  "
              f"Rate: {ok/max(total,1)*100:.0f}%")

        summary_path = os.path.join(run_dir, "summary.json")
        with open(summary_path, "w") as f:
            json.dump(all_results, f, indent=2)
        print(f"\n  📁 Run saved to: {run_dir}")

    print()
    print("══════════════════════════════════════════════════════════")
    print("  UNIFIED VLA AGENT v1.1 — DONE")
    print("══════════════════════════════════════════════════════════")


if __name__ == "__main__":
    main()
