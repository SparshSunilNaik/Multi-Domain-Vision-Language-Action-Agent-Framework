#!/usr/bin/env python3
"""
Unified VLA Agent — Multi-Domain Interactive Web Navigator.

Supports: Forum, GitLab, Wikipedia, Store, Booking, and public sites.
Uses Ollama qwen3:8b via /api/chat with think:false.
DOM extraction via JS with data-vla-id injection.
No safety gating. Pure autonomy.

Usage:
    python vla_unified_agent.py                          # Interactive mode
    python vla_unified_agent.py --scenarios file.json    # Scenario-file mode
    python vla_unified_agent.py --builtin                # Built-in test scenarios
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
MAX_CLICKABLE = 15
MAX_TYPEABLE  = 5
MAX_TEXT_LEN  = 80
SAME_URL_LIMIT = 6

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
#  JS DOM Extraction — data-vla-id injection
# ═══════════════════════════════════════════════════════════════
EXTRACT_JS = """
() => {
    const results = [];
    const seen = new Set();
    let counter = 0;

    function isVisible(el) {
        if (!el.offsetParent && el.tagName !== 'BODY' && el.tagName !== 'HTML') return false;
        const r = el.getBoundingClientRect();
        if (r.width === 0 || r.height === 0) return false;
        if (r.bottom < 0 || r.top > window.innerHeight) return false;
        if (r.right < 0 || r.left > window.innerWidth) return false;
        const s = window.getComputedStyle(el);
        if (s.display === 'none' || s.visibility === 'hidden') return false;
        if (parseFloat(s.opacity) < 0.1) return false;
        return true;
    }

    function getLabel(el) {
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

    // Clickable
    document.querySelectorAll(
        'a[href], button, [role="button"], [role="link"], [role="menuitem"], ' +
        '[role="tab"], [role="option"], [onclick], summary, [role="treeitem"]'
    ).forEach(el => {
        if (!isVisible(el)) return;
        const label = getLabel(el);
        if (!label || label.length < 1) return;
        const key = 'c:' + label.toLowerCase().substring(0, 40);
        if (seen.has(key)) return;
        seen.add(key);
        const vid = tag(el);
        results.push({
            vla_id: vid, kind: 'clickable',
            tag: el.tagName.toLowerCase(),
            role: el.getAttribute('role') || (el.tagName === 'A' ? 'link' : 'button'),
            label: label,
            input_type: null,
        });
    });

    // Typeable
    document.querySelectorAll(
        'input[type="text"], input[type="search"], input[type="email"], ' +
        'input[type="password"], input[type="url"], input[type="tel"], ' +
        'input[type="number"], input:not([type]), textarea, ' +
        '[contenteditable="true"], [role="textbox"], [role="searchbox"], [role="combobox"]'
    ).forEach(el => {
        if (!isVisible(el)) return;
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
def build_prompt(instruction, url, clickable, typeable, last_action):
    cl = "\n".join(f'  [{e["vla_id"]}] {e["role"]} "{e["label"]}"'
                   for e in clickable) or "  (none)"
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

    # TYPE <id> "text"  or  TYPE <id> 'text'  or  TYPE <id> text
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
            break  # matched pattern but bad id — fall through

    # CLICK <id>
    m = re.search(r'CLICK\s+(\S+)', response, re.IGNORECASE)
    if m:
        eid = m.group(1).strip("[]\"'")
        if eid in all_el:
            return {"type": "CLICK", "id": eid, "element": all_el[eid]}

    # ── Deterministic fallback ──
    # If there's a typeable search box, type the search term
    for e in typeable:
        lbl = e["label"].lower()
        if any(k in lbl for k in ("search", "query", "find")):
            return {"type": "CLICK", "id": str(e["vla_id"]),
                    "element": e, "fallback": True}
    # Otherwise first clickable
    if clickable:
        return {"type": "CLICK", "id": str(clickable[0]["vla_id"]),
                "element": clickable[0], "fallback": True}
    if typeable:
        return {"type": "CLICK", "id": str(typeable[0]["vla_id"]),
                "element": typeable[0], "fallback": True}
    return {"type": "STOP"}


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
        try:
            h = page.query_selector(sel)
            if h:
                h.click(); time.sleep(0.1)
                h.fill(text); time.sleep(0.1)
                h.press("Enter"); time.sleep(0.8)
                return f'TYPE [{vid}] "{label}" ← "{text}"'
            page.keyboard.type(text, delay=25)
            page.keyboard.press("Enter"); time.sleep(0.5)
            return f'TYPE (keyboard) ← "{text}"'
        except Exception as e:
            try:
                page.keyboard.type(text, delay=25)
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
    """Returns (done: bool, reason: str)."""
    u = url.lower()

    # Google captcha / sorry page
    if domain == "google" and "/sorry/" in u:
        return True, "BLOCKED: Google captcha (/sorry/). Try Bing or DuckDuckGo."

    # Keyword match (URL, title, or page text)
    if keyword:
        kw = keyword.lower()
        if kw in u:
            return True, f"Keyword '{keyword}' found in URL"
        if kw in page_title.lower():
            return True, f"Keyword '{keyword}' found in page title"
        if len(kw) >= 8 and kw in page_text_snippet.lower():
            return True, f"Keyword '{keyword}' found in page text"

    # Wikipedia
    if domain == "wikipedia" and "/wiki/" in u:
        slug = u.split("/wiki/")[-1].split("?")[0].split("#")[0]
        if slug and slug != "main_page" and slug != "special:search":
            return True, f"Wikipedia article loaded: /wiki/{slug}"

    # YouTube search
    if domain == "youtube" and "results?search_query=" in u:
        return True, "YouTube search results loaded"

    # Store / Booking success markers
    if domain in ("store", "booking"):
        for marker in ("vla_order_success", "vla_booking_success",
                        "confirmation", "order confirmed",
                        "thank you for your order", "booking confirmed"):
            if marker in page_text_snippet.lower():
                return True, f"Success marker found: {marker}"

    return False, ""


def get_page_text_snippet(page, length=500):
    """Get first N chars of visible body text."""
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
#  Run Single Scenario
# ═══════════════════════════════════════════════════════════════
def run_scenario(page, name, instruction, start_url, keyword,
                 max_steps, run_dir):
    """Execute one scenario. Returns result dict."""
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

    trace = []  # per-step JSON trace
    result = {
        "name": name, "instruction": instruction, "start_url": start_url,
        "domain": domain, "keyword": keyword,
        "steps_taken": 0, "final_url": "", "success": False, "reason": "",
    }

    # Navigate
    try:
        page.goto(start_url, wait_until="domcontentloaded", timeout=15000)
        time.sleep(2.0)
    except Exception as e:
        result["reason"] = f"Navigation failed: {str(e)[:50]}"
        print(f"  ❌ {result['reason']}")
        return result

    dismiss_banners(page)

    # GitLab login if needed
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

    for step in range(1, max_steps + 1):
        cur_url = page.url
        url_history.append(cur_url)
        title = ""
        try: title = page.title()
        except Exception: pass
        text_snip = get_page_text_snippet(page)

        # ── Completion check ──
        done, reason = check_completion(
            instruction, cur_url, title, text_snip, keyword, domain)
        if done:
            # Screenshot
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

        # ── Same-URL loop detection ──
        if len(url_history) >= SAME_URL_LIMIT:
            recent = url_history[-SAME_URL_LIMIT:]
            if len(set(recent)) == 1:
                result.update(steps_taken=step, final_url=cur_url,
                              reason="Stopped: same URL repeated >6 times")
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

        # ── LLM action ──
        prompt = build_prompt(instruction, cur_url, clickable, typeable,
                              last_action)
        t0 = time.time()
        raw = llm_query(prompt)
        lat = time.time() - t0

        action = parse_action(raw, clickable, typeable)

        if action["type"] == "STOP":
            result.update(steps_taken=step, final_url=cur_url,
                          reason="LLM output STOP")
            # Check if actually succeeded
            d, r = check_completion(instruction, cur_url, title,
                                     text_snip, keyword, domain)
            if d: result.update(success=True, reason=r)
            print(f"  Step {step:>2} │ STOP  (LLM)")
            break

        # ── Execute ──
        action_desc = execute(page, action)
        last_action = action_desc
        fb = " ⟵fallback" if action.get("fallback") else ""

        elem_info = action.get("element", {})
        step_data = {
            "step": step, "url": cur_url,
            "action_type": action["type"],
            "action_desc": action_desc,
            "element_label": elem_info.get("label", ""),
            "element_vla_id": action.get("id", ""),
            "llm_raw": raw[:100], "llm_latency": round(lat, 2),
            "fallback": bool(action.get("fallback")),
            "n_clickable": len(clickable), "n_typeable": len(typeable),
        }
        trace.append(step_data)

        print(f"  Step {step:>2} │ {action_desc[:55]:<55} │ "
              f"{lat:.1f}s{fb}")

        result["steps_taken"] = step
        result["final_url"] = page.url
        time.sleep(0.2)

    else:
        # Loop ended normally (max steps)
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
    ap = argparse.ArgumentParser(description="Unified VLA Agent")
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

    # Determine mode and scenarios
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

    # Run directory
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = os.path.join(SCRIPT_DIR, "runs", ts)
    os.makedirs(run_dir, exist_ok=True)

    print()
    print("══════════════════════════════════════════════════════════")
    print("  UNIFIED VLA AGENT")
    print("══════════════════════════════════════════════════════════")
    print(f"  Model:     {MODEL_NAME} (temp={TEMPERATURE})")
    print(f"  API:       /api/chat (think=false)")
    print(f"  Headless:  {headless}")
    print(f"  Mode:      {mode_label}")
    print(f"  Run dir:   {run_dir}")
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
                # ── Batch mode ──
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
                # ── Interactive mode ──
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
        print("  RESULTS SUMMARY")
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

        # Save summary
        summary_path = os.path.join(run_dir, "summary.json")
        with open(summary_path, "w") as f:
            json.dump(all_results, f, indent=2)
        print(f"\n  📁 Run saved to: {run_dir}")

    print()
    print("══════════════════════════════════════════════════════════")
    print("  UNIFIED VLA AGENT — DONE")
    print("══════════════════════════════════════════════════════════")


if __name__ == "__main__":
    main()
