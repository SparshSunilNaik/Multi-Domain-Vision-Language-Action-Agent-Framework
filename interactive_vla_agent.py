#!/usr/bin/env python3
"""
Interactive VLA Agent — Dual-Mode Prototype.

Standalone Vision-Language-Action agent using Playwright + Ollama.
No safety gating. No verifier. Pure autonomy mode.

Uses JavaScript-based DOM extraction (not accessibility tree API)
for robust element discovery on modern web pages.

Usage:
    python interactive_vla_agent.py            # Interactive mode
    python interactive_vla_agent.py --auto     # Auto scenarios mode
"""

import argparse
import json
import os
import re
import sys
import time
import urllib.request
import urllib.error

# ═══════════════════════════════════════════════════════════════
#  Config
# ═══════════════════════════════════════════════════════════════
OLLAMA_URL = "http://localhost:11434/api/generate"
MODEL_NAME = "qwen3:8b"
TEMPERATURE = 0.7
NUM_PREDICT_ACTION = 80
NUM_PREDICT_CHECK = 5
MAX_STEPS = 20
MAX_CLICKABLE = 15
MAX_TYPEABLE = 5
MAX_TEXT_LENGTH = 80
LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       "interactive_logs")

# ═══════════════════════════════════════════════════════════════
#  Auto Scenarios
# ═══════════════════════════════════════════════════════════════
AUTO_SCENARIOS = [
    {
        "instruction": "Go to google.com and search for 'docker tutorial'",
        "start_url": "https://www.google.com",
        "completion_url_keyword": "search",
    },
    {
        "instruction": "Go to youtube.com and search for 'machine learning basics'",
        "start_url": "https://www.youtube.com",
        "completion_url_keyword": "results",
    },
    {
        "instruction": "Go to github.com",
        "start_url": "https://github.com",
        "completion_url_keyword": "github.com",
    },
]

# ═══════════════════════════════════════════════════════════════
#  JS snippet to extract visible interactive elements from DOM
# ═══════════════════════════════════════════════════════════════
EXTRACT_ELEMENTS_JS = """
() => {
    const results = [];
    const seen = new Set();

    function isVisible(el) {
        if (!el.offsetParent && el.tagName !== 'BODY') return false;
        const r = el.getBoundingClientRect();
        if (r.width === 0 || r.height === 0) return false;
        if (r.bottom < 0 || r.top > window.innerHeight) return false;
        if (r.right < 0 || r.left > window.innerWidth) return false;
        const style = window.getComputedStyle(el);
        if (style.display === 'none' || style.visibility === 'hidden') return false;
        if (parseFloat(style.opacity) < 0.1) return false;
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

    // Inject unique data attribute for reliable selection
    let vla_counter = 0;
    function tagElement(el) {
        vla_counter++;
        el.setAttribute('data-vla-id', String(vla_counter));
        return '[data-vla-id="' + vla_counter + '"]';
    }

    // Clickable elements
    const clickSelectors = 'a[href], button, [role="button"], [role="link"], ' +
        '[role="menuitem"], [role="tab"], [role="option"], [onclick], ' +
        'summary, [role="treeitem"]';
    document.querySelectorAll(clickSelectors).forEach((el, i) => {
        if (!isVisible(el)) return;
        const label = getLabel(el);
        if (!label || label.length < 1) return;
        const key = 'click:' + label.toLowerCase().substring(0, 40);
        if (seen.has(key)) return;
        seen.add(key);
        results.push({
            type: 'clickable',
            tag: el.tagName.toLowerCase(),
            label: label,
            selector: tagElement(el),
            role: el.getAttribute('role') || (el.tagName === 'A' ? 'link' : 'button'),
        });
    });

    // Typeable elements
    const typeSelectors = 'input[type="text"], input[type="search"], ' +
        'input[type="email"], input[type="password"], input[type="url"], ' +
        'input[type="tel"], input[type="number"], input:not([type]), ' +
        'textarea, [contenteditable="true"], ' +
        '[role="textbox"], [role="searchbox"], [role="combobox"]';
    document.querySelectorAll(typeSelectors).forEach((el, i) => {
        if (!isVisible(el)) return;
        const label = getLabel(el);
        const displayLabel = label || el.getAttribute('type') || 'text input';
        const key = 'type:' + displayLabel.toLowerCase().substring(0, 40);
        if (seen.has(key)) return;
        seen.add(key);
        results.push({
            type: 'typeable',
            tag: el.tagName.toLowerCase(),
            label: displayLabel,
            selector: tagElement(el),
            role: el.getAttribute('role') || 'textbox',
        });
    });

    return results;
}
"""


# ═══════════════════════════════════════════════════════════════
#  Ollama Query
# ═══════════════════════════════════════════════════════════════
def query_ollama(prompt, max_tokens=NUM_PREDICT_ACTION):
    # Use chat API with think=false to disable qwen3 CoT
    payload = json.dumps({
        "model": MODEL_NAME,
        "messages": [
            {"role": "user", "content": prompt}
        ],
        "stream": False,
        "think": False,
        "options": {
            "temperature": TEMPERATURE,
            "num_predict": max_tokens,
        },
    }).encode("utf-8")

    chat_url = OLLAMA_URL.replace("/api/generate", "/api/chat")

    req = urllib.request.Request(
        chat_url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            body = json.loads(resp.read().decode("utf-8"))
            msg = body.get("message", {})
            raw = msg.get("content", "").strip()
            # Safety: strip any residual thinking tags
            raw = re.sub(r'<think>.*?</think>', '', raw, flags=re.DOTALL).strip()
            return raw
    except Exception as e:
        return f"ERROR: {e}"


# ═══════════════════════════════════════════════════════════════
#  Element Extraction
# ═══════════════════════════════════════════════════════════════
def extract_elements(page):
    """Extract interactive elements via JS evaluation."""
    try:
        raw = page.evaluate(EXTRACT_ELEMENTS_JS)
    except Exception as e:
        print(f"      [extract] JS error: {str(e)[:50]}")
        return [], []

    if not raw:
        return [], []

    clickable = []
    typeable = []

    for i, el in enumerate(raw):
        el["id"] = str(i + 1)
        if el["type"] == "clickable":
            clickable.append(el)
        elif el["type"] == "typeable":
            typeable.append(el)

    return clickable[:MAX_CLICKABLE], typeable[:MAX_TYPEABLE]


# ═══════════════════════════════════════════════════════════════
#  Prompt Builder
# ═══════════════════════════════════════════════════════════════
def build_prompt(instruction, current_url, clickable, typeable, last_action):
    click_lines = "\n".join(
        f'  [{e["id"]}] {e["role"]} "{e["label"]}"'
        for e in clickable
    ) or "  (none)"

    type_lines = "\n".join(
        f'  [{e["id"]}] {e["role"]} "{e["label"]}"'
        for e in typeable
    ) or "  (none)"

    last = f"\nLast action: {last_action}" if last_action else ""

    return f"""You are a web navigation agent.

Instruction: "{instruction}"

URL: {current_url}{last}

Clickable:
{click_lines}

Typeable:
{type_lines}

Choose one action:
CLICK <id>
TYPE <id> "<text>"
DONE

Output only the action. /no_think"""


# ═══════════════════════════════════════════════════════════════
#  Action Parser
# ═══════════════════════════════════════════════════════════════
def parse_action(response, clickable, typeable):
    all_elements = clickable + typeable
    id_map = {e["id"]: e for e in all_elements}

    if re.search(r'\bDONE\b', response, re.IGNORECASE):
        return {"type": "DONE"}

    # Try TYPE
    m = re.search(r'TYPE\s+(\S+)\s+"([^"]*)"', response, re.IGNORECASE)
    if not m:
        m = re.search(r"TYPE\s+(\S+)\s+'([^']*)'", response, re.IGNORECASE)
    if not m:
        m = re.search(r'TYPE\s+(\S+)\s+(\S+)', response, re.IGNORECASE)
    if m:
        eid = m.group(1).strip("[]")
        text = m.group(2).replace("\n", " ").strip()[:MAX_TEXT_LENGTH]
        if eid in id_map and text:
            return {"type": "TYPE", "id": eid, "text": text,
                    "element": id_map[eid]}

    # Try CLICK
    m = re.search(r'CLICK\s+(\S+)', response, re.IGNORECASE)
    if m:
        eid = m.group(1).strip("[]").strip('"').strip("'")
        if eid in id_map:
            return {"type": "CLICK", "id": eid,
                    "element": id_map[eid]}

    # Fallback: first clickable or typeable
    if clickable:
        return {"type": "CLICK", "id": clickable[0]["id"],
                "element": clickable[0], "fallback": True}
    if typeable:
        return {"type": "CLICK", "id": typeable[0]["id"],
                "element": typeable[0], "fallback": True}

    return {"type": "DONE"}


# ═══════════════════════════════════════════════════════════════
#  Completion Check
# ═══════════════════════════════════════════════════════════════
def check_completion(instruction, current_url):
    prompt = (
        f'Instruction: "{instruction}"\n'
        f'Current URL: {current_url}\n\n'
        f'Has the main objective been completed? YES or NO.'
    )
    resp = query_ollama(prompt, max_tokens=NUM_PREDICT_CHECK)
    return "YES" in resp.upper()


# ═══════════════════════════════════════════════════════════════
#  Execute Action in Browser
# ═══════════════════════════════════════════════════════════════
def execute_action(page, action):
    if action["type"] == "DONE":
        return "DONE"

    elem = action.get("element", {})
    selector = elem.get("selector", "")
    label = elem.get("label", "unknown")

    if action["type"] == "TYPE":
        text = action["text"]
        try:
            handle = page.query_selector(selector)
            if handle:
                handle.click()
                time.sleep(0.15)
                handle.fill(text)
                time.sleep(0.15)
                # Press Enter for search-like inputs
                if any(kw in label.lower() for kw in
                       ("search", "query", "find")):
                    handle.press("Enter")
                    time.sleep(0.8)
                else:
                    handle.press("Enter")
                    time.sleep(0.3)
                return f'TYPE "{label}" ← "{text}"'
            else:
                # Fallback: keyboard type
                page.keyboard.type(text, delay=30)
                page.keyboard.press("Enter")
                time.sleep(0.3)
                return f'TYPE (keyboard) ← "{text}"'
        except Exception as e:
            try:
                page.keyboard.type(text, delay=30)
                page.keyboard.press("Enter")
                time.sleep(0.3)
                return f'TYPE (keyboard fallback) ← "{text}"'
            except Exception:
                return f'TYPE FAILED: {str(e)[:40]}'

    elif action["type"] == "CLICK":
        try:
            handle = page.query_selector(selector)
            if handle:
                handle.scroll_into_view_if_needed(timeout=3000)
                time.sleep(0.1)
                handle.click(timeout=5000)
                time.sleep(0.5)
                return f'CLICK "{label}"'
            else:
                # Try text-based
                loc = page.get_by_text(label, exact=False)
                if loc.count() > 0:
                    loc.first.click(timeout=5000)
                    time.sleep(0.5)
                    return f'CLICK (text) "{label}"'
                return f'CLICK SKIP: "{label}" not found'
        except Exception as e:
            return f'CLICK FAILED: {str(e)[:40]}'

    return "UNKNOWN"


# ═══════════════════════════════════════════════════════════════
#  Dismiss Cookie / Consent Banners
# ═══════════════════════════════════════════════════════════════
def dismiss_banners(page):
    """Try to dismiss common cookie/consent banners."""
    selectors = [
        'button:text("Accept")',
        'button:text("Accept all")',
        'button:text("I agree")',
        'button:text("Reject all")',
        'button:text("Got it")',
        '[aria-label="Accept"]',
        '[id*="accept"]',
        '#L2AGLb',  # Google consent
        'button.VfPpkd-LgbsSe',  # Google material button
    ]
    for sel in selectors:
        try:
            loc = page.locator(sel)
            if loc.count() > 0:
                loc.first.click(timeout=2000)
                time.sleep(0.5)
                print("      [banner dismissed]")
                return True
        except Exception:
            continue
    return False


# ═══════════════════════════════════════════════════════════════
#  Run Single Scenario
# ═══════════════════════════════════════════════════════════════
def run_scenario(page, instruction, start_url, completion_keyword,
                 scenario_idx, screenshot_prefix):

    print(f"\n{'=' * 60}")
    print(f"  Scenario {scenario_idx}: {instruction}")
    print(f"  Start: {start_url}")
    print(f"  Completion keyword: '{completion_keyword}'")
    print(f"{'=' * 60}")

    try:
        page.goto(start_url, wait_until="domcontentloaded", timeout=15000)
        time.sleep(2.0)
    except Exception as e:
        print(f"  ❌ Navigation failed: {str(e)[:60]}")
        return

    # Dismiss any consent banners
    dismiss_banners(page)

    last_action = None
    completed = False

    for step in range(1, MAX_STEPS + 1):
        current_url = page.url

        # ── Check URL-based completion ──
        if (completion_keyword
                and completion_keyword.lower() in current_url.lower()):
            # Take final screenshot
            ss = os.path.join(
                LOG_DIR, f"{screenshot_prefix}_step{step:02d}_done.png")
            try:
                page.screenshot(path=ss)
            except Exception:
                pass
            print(f"\n  🎯 URL pattern '{completion_keyword}' detected!")
            print(f"\n  ✅ Scenario completed early.")
            print(f"  Steps taken: {step - 1}")
            print(f"  Final URL: {current_url}")
            return

        # ── Screenshot ──
        ss_path = os.path.join(
            LOG_DIR, f"{screenshot_prefix}_step{step:02d}.png")
        try:
            page.screenshot(path=ss_path)
        except Exception:
            pass

        # ── Extract elements ──
        clickable, typeable = extract_elements(page)

        if not clickable and not typeable:
            print(f"    Step {step:>2}/{MAX_STEPS} │ "
                  f"No elements — scrolling & retrying")
            page.keyboard.press("PageDown")
            time.sleep(1.0)
            # Try again after scroll
            clickable, typeable = extract_elements(page)
            if not clickable and not typeable:
                # Try dismissing banners
                dismiss_banners(page)
                time.sleep(0.5)
                clickable, typeable = extract_elements(page)

        if not clickable and not typeable:
            print(f"    Step {step:>2}/{MAX_STEPS} │ "
                  f"Still no elements — skipping step")
            continue

        # ── Build prompt and query LLM ──
        prompt = build_prompt(
            instruction, current_url, clickable, typeable, last_action)

        t0 = time.time()
        raw_response = query_ollama(prompt, NUM_PREDICT_ACTION)
        latency = time.time() - t0

        # ── Parse action ──
        action = parse_action(raw_response, clickable, typeable)

        if action["type"] == "DONE":
            print(f"\n    ---------------------------------")
            print(f"    Scenario: {instruction[:50]}")
            print(f"    Step: {step}")
            print(f"    URL: {current_url[:60]}")
            print(f"    Chosen Action: DONE")
            print(f"    ---------------------------------")
            print(f"\n  ✅ Scenario completed (LLM: DONE).")
            print(f"  Steps taken: {step}")
            print(f"  Final URL: {current_url}")
            return

        # ── Execute action ──
        result = execute_action(page, action)
        last_action = result

        fb = " (fallback)" if action.get("fallback") else ""
        print(f"    ---------------------------------")
        print(f"    Scenario: {instruction[:50]}")
        print(f"    Step: {step}")
        print(f"    URL: {current_url[:60]}")
        print(f"    Chosen Action: {result}{fb}")
        print(f"    LLM ({latency:.1f}s): {raw_response[:60]}")
        print(f"    ---------------------------------")

        time.sleep(0.3)

        # ── Post-step URL check ──
        new_url = page.url
        if (completion_keyword
                and completion_keyword.lower() in new_url.lower()):
            final_ss = os.path.join(
                LOG_DIR,
                f"{screenshot_prefix}_step{step+1:02d}_done.png")
            try:
                page.screenshot(path=final_ss)
            except Exception:
                pass

            print(f"\n  🎯 URL pattern '{completion_keyword}' detected!")
            print(f"\n  ✅ Scenario completed early.")
            print(f"  Steps taken: {step}")
            print(f"  Final URL: {new_url}")
            return

        # ── LLM completion check (every 4 steps) ──
        if step % 4 == 0:
            if check_completion(instruction, new_url):
                final_ss = os.path.join(
                    LOG_DIR,
                    f"{screenshot_prefix}_step{step+1:02d}_done.png")
                try:
                    page.screenshot(path=final_ss)
                except Exception:
                    pass
                print(f"\n  ✅ Scenario completed (LLM confirmed).")
                print(f"  Steps taken: {step}")
                print(f"  Final URL: {new_url}")
                return

    print(f"\n  ⚠️  Max steps ({MAX_STEPS}) reached.")
    print(f"  Steps taken: {MAX_STEPS}")
    print(f"  Final URL: {page.url}")


# ═══════════════════════════════════════════════════════════════
#  Main
# ═══════════════════════════════════════════════════════════════
def main():
    parser = argparse.ArgumentParser(
        description="Interactive VLA Agent — Dual Mode")
    parser.add_argument("--auto", action="store_true",
                        help="Run predefined auto scenarios")
    args = parser.parse_args()

    os.makedirs(LOG_DIR, exist_ok=True)

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("❌ Playwright not installed. Run: pip install playwright")
        sys.exit(1)

    print()
    print("══════════════════════════════════════════")
    print("  INTERACTIVE VLA AGENT")
    print("══════════════════════════════════════════")
    print(f"  Model:      {MODEL_NAME}")
    print(f"  Temp:       {TEMPERATURE}")
    print(f"  Max steps:  {MAX_STEPS}")
    print(f"  Mode:       {'AUTO' if args.auto else 'INTERACTIVE'}")
    print(f"  Screenshots: {LOG_DIR}")
    print(f"  Safety:     NONE (pure autonomy)")
    print("══════════════════════════════════════════")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context(
            viewport={"width": 1280, "height": 720},
            locale="en-US",
        )

        try:
            if args.auto:
                for idx, scenario in enumerate(AUTO_SCENARIOS, 1):
                    page = context.new_page()
                    try:
                        run_scenario(
                            page,
                            scenario["instruction"],
                            scenario["start_url"],
                            scenario["completion_url_keyword"],
                            idx,
                            f"scenario{idx}",
                        )
                    finally:
                        try:
                            page.close()
                        except Exception:
                            pass

                    if idx < len(AUTO_SCENARIOS):
                        print(f"\n  💤 Sleeping 2s before next scenario...")
                        time.sleep(2)
            else:
                scenario_count = 0
                while True:
                    print()
                    try:
                        instruction = input(
                            "Enter instruction (or 'quit'): ").strip()
                    except (EOFError, KeyboardInterrupt):
                        print("\n  Goodbye!")
                        break

                    if not instruction or instruction.lower() in (
                            "quit", "exit", "q"):
                        print("  Goodbye!")
                        break

                    try:
                        start_url = input(
                            "Start URL [https://www.google.com]: ").strip()
                    except (EOFError, KeyboardInterrupt):
                        print("\n  Goodbye!")
                        break
                    if not start_url:
                        start_url = "https://www.google.com"

                    try:
                        keyword = input(
                            "Completion URL keyword (optional): ").strip()
                    except (EOFError, KeyboardInterrupt):
                        print("\n  Goodbye!")
                        break

                    scenario_count += 1
                    page = context.new_page()
                    try:
                        run_scenario(
                            page, instruction, start_url,
                            keyword if keyword else None,
                            scenario_count,
                            f"interactive{scenario_count}",
                        )
                    finally:
                        try:
                            page.close()
                        except Exception:
                            pass

        finally:
            try:
                context.close()
                browser.close()
            except Exception:
                pass

    print()
    print("══════════════════════════════════════════")
    print("INTERACTIVE VLA PROTOTYPE READY")
    print("Dual mode supported (--auto)")
    print("Visible browser enabled")
    print("No safety gating active")
    print("Screenshots saved to interactive_logs/")
    print("Token-efficient execution enabled")
    print("══════════════════════════════════════════")


if __name__ == "__main__":
    main()
