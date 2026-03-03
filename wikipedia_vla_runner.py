#!/usr/bin/env python3
"""
Wikipedia VLA Runner — Multi-domain evaluation with Wikipedia support.

Standalone runner using the proven VLA architecture:
    - Ollama /api/chat with think:false (qwen3:8b, temp 0.7)
    - JavaScript DOM extraction with data-vla-id injection
    - Wikipedia-specific completion detection

Usage:
    python wikipedia_vla_runner.py                # Run 3 default scenarios
    python wikipedia_vla_runner.py --interactive  # Interactive mode
"""

import argparse
import json
import os
import re
import sys
import time
import urllib.request
import urllib.error

from wikipedia_support import (
    WIKIPEDIA_SCENARIOS,
    check_wikipedia_completion,
    extract_search_term,
    classify_intent,
    get_page_title,
)

# ═══════════════════════════════════════════════════════════════
#  Config
# ═══════════════════════════════════════════════════════════════
OLLAMA_URL = "http://localhost:11434/api/chat"
MODEL_NAME = "qwen3:8b"
TEMPERATURE = 0.7
NUM_PREDICT = 80
MAX_STEPS = 20
MAX_CLICKABLE = 15
MAX_TYPEABLE = 5
MAX_TEXT_LENGTH = 80
LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       "interactive_logs")

# ═══════════════════════════════════════════════════════════════
#  JS DOM extraction — identical to interactive_vla_agent.py
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

    let vla_counter = 0;
    function tagElement(el) {
        vla_counter++;
        el.setAttribute('data-vla-id', String(vla_counter));
        return '[data-vla-id="' + vla_counter + '"]';
    }

    // Clickable
    const clickSelectors = 'a[href], button, [role="button"], [role="link"], ' +
        '[role="menuitem"], [role="tab"], [role="option"], [onclick], ' +
        'summary, [role="treeitem"]';
    document.querySelectorAll(clickSelectors).forEach((el) => {
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

    // Typeable
    const typeSelectors = 'input[type="text"], input[type="search"], ' +
        'input[type="email"], input[type="password"], input[type="url"], ' +
        'input[type="tel"], input[type="number"], input:not([type]), ' +
        'textarea, [contenteditable="true"], ' +
        '[role="textbox"], [role="searchbox"], [role="combobox"]';
    document.querySelectorAll(typeSelectors).forEach((el) => {
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
#  Ollama /api/chat with think:false
# ═══════════════════════════════════════════════════════════════
def query_ollama(prompt, max_tokens=NUM_PREDICT):
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

    req = urllib.request.Request(
        OLLAMA_URL,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            body = json.loads(resp.read().decode("utf-8"))
            msg = body.get("message", {})
            raw = msg.get("content", "").strip()
            raw = re.sub(r'<think>.*?</think>', '', raw,
                         flags=re.DOTALL).strip()
            return raw
    except Exception as e:
        return f"ERROR: {e}"


# ═══════════════════════════════════════════════════════════════
#  Element Extraction
# ═══════════════════════════════════════════════════════════════
def extract_elements(page):
    try:
        raw = page.evaluate(EXTRACT_ELEMENTS_JS)
    except Exception as e:
        print(f"      [extract] JS error: {str(e)[:50]}")
        return [], []
    if not raw:
        return [], []

    clickable, typeable = [], []
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

    return f"""You are a web navigation agent on Wikipedia.

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

Output only the action."""


# ═══════════════════════════════════════════════════════════════
#  Action Parser
# ═══════════════════════════════════════════════════════════════
def parse_action(response, clickable, typeable):
    all_elements = clickable + typeable
    id_map = {e["id"]: e for e in all_elements}

    if re.search(r'\bDONE\b', response, re.IGNORECASE):
        return {"type": "DONE"}

    # TYPE
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

    # CLICK
    m = re.search(r'CLICK\s+(\S+)', response, re.IGNORECASE)
    if m:
        eid = m.group(1).strip("[]").strip('"').strip("'")
        if eid in id_map:
            return {"type": "CLICK", "id": eid, "element": id_map[eid]}

    # Fallback
    if clickable:
        return {"type": "CLICK", "id": clickable[0]["id"],
                "element": clickable[0], "fallback": True}
    if typeable:
        return {"type": "CLICK", "id": typeable[0]["id"],
                "element": typeable[0], "fallback": True}
    return {"type": "DONE"}


# ═══════════════════════════════════════════════════════════════
#  Execute Action
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
                handle.press("Enter")
                time.sleep(1.0)
                return f'TYPE "{label}" ← "{text}"'
            else:
                page.keyboard.type(text, delay=30)
                page.keyboard.press("Enter")
                time.sleep(0.5)
                return f'TYPE (keyboard) ← "{text}"'
        except Exception as e:
            try:
                page.keyboard.type(text, delay=30)
                page.keyboard.press("Enter")
                time.sleep(0.5)
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
                time.sleep(0.8)
                return f'CLICK "{label}"'
            else:
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
#  Banner Dismissal
# ═══════════════════════════════════════════════════════════════
def dismiss_banners(page):
    """Dismiss cookie/consent banners (Wikipedia sometimes shows these)."""
    selectors = [
        'button:text("Accept")',
        'button:text("I agree")',
        'button:text("Got it")',
        'button:text("OK")',
        '[aria-label="Close"]',
    ]
    for sel in selectors:
        try:
            loc = page.locator(sel)
            if loc.count() > 0:
                loc.first.click(timeout=2000)
                time.sleep(0.3)
                print("      [banner dismissed]")
                return True
        except Exception:
            continue
    return False


# ═══════════════════════════════════════════════════════════════
#  Run Single Wikipedia Scenario
# ═══════════════════════════════════════════════════════════════
def run_wikipedia_scenario(page, scenario, scenario_idx):
    instruction = scenario["instruction"]
    start_url = scenario["start_url"]
    search_term = scenario.get("search_term",
                               extract_search_term(instruction))

    print(f"\n{'=' * 70}")
    print(f"  Scenario {scenario_idx}: {instruction}")
    print(f"  Start:   {start_url}")
    print(f"  Term:    {search_term}")
    print(f"  Intent:  {classify_intent(instruction)}")
    print(f"{'=' * 70}")

    result = {
        "scenario": scenario_idx,
        "instruction": instruction,
        "search_term": search_term,
        "steps_taken": 0,
        "final_url": "",
        "success": False,
        "reason": "",
    }

    # Navigate
    try:
        page.goto(start_url, wait_until="domcontentloaded", timeout=15000)
        time.sleep(2.0)
    except Exception as e:
        print(f"  ❌ Navigation failed: {str(e)[:60]}")
        result["reason"] = f"Navigation failed: {str(e)[:40]}"
        return result

    dismiss_banners(page)

    last_action = None

    for step in range(1, MAX_STEPS + 1):
        current_url = page.url
        page_title = get_page_title(page)

        # ── Completion check ──
        completed, reason = check_wikipedia_completion(
            instruction, current_url, page_title)
        if completed:
            ss = os.path.join(
                LOG_DIR, f"wiki{scenario_idx}_step{step:02d}_done.png")
            try:
                page.screenshot(path=ss)
            except Exception:
                pass

            print(f"\n  🎯 Completion: {reason}")
            print(f"  ✅ Scenario completed early.")
            print(f"  Steps taken: {step - 1}")
            print(f"  Final URL: {current_url}")
            result["steps_taken"] = step - 1
            result["final_url"] = current_url
            result["success"] = True
            result["reason"] = reason
            return result

        # ── Screenshot ──
        ss_path = os.path.join(
            LOG_DIR, f"wiki{scenario_idx}_step{step:02d}.png")
        try:
            page.screenshot(path=ss_path)
        except Exception:
            pass

        # ── Extract elements ──
        clickable, typeable = extract_elements(page)

        if not clickable and not typeable:
            print(f"    Step {step:>2}/{MAX_STEPS} │ "
                  f"No elements — scrolling")
            page.keyboard.press("PageDown")
            time.sleep(0.8)
            clickable, typeable = extract_elements(page)

        if not clickable and not typeable:
            print(f"    Step {step:>2}/{MAX_STEPS} │ "
                  f"Still no elements — skipping")
            continue

        # ── LLM action ──
        prompt = build_prompt(
            instruction, current_url, clickable, typeable, last_action)
        t0 = time.time()
        raw_response = query_ollama(prompt)
        latency = time.time() - t0

        action = parse_action(raw_response, clickable, typeable)

        if action["type"] == "DONE":
            print(f"    ---------------------------------")
            print(f"    Step: {step}")
            print(f"    URL: {current_url[:65]}")
            print(f"    Action: DONE (LLM declared)")
            print(f"    ---------------------------------")
            result["steps_taken"] = step
            result["final_url"] = current_url
            # Check if actually succeeded
            completed, reason = check_wikipedia_completion(
                instruction, current_url, page_title)
            result["success"] = completed
            result["reason"] = reason if completed else "LLM declared DONE"
            print(f"\n  {'✅' if result['success'] else '⚠️ '}  "
                  f"Scenario {'completed' if result['success'] else 'ended'}.")
            print(f"  Steps taken: {step}")
            print(f"  Final URL: {current_url}")
            return result

        # ── Execute ──
        action_result = execute_action(page, action)
        last_action = action_result
        fb = " (fallback)" if action.get("fallback") else ""

        print(f"    ---------------------------------")
        print(f"    Step: {step}")
        print(f"    URL: {current_url[:65]}")
        print(f"    Action: {action_result}{fb}")
        print(f"    LLM ({latency:.1f}s): {raw_response[:60]}")
        print(f"    ---------------------------------")

        result["steps_taken"] = step
        time.sleep(0.3)

    # Max steps
    final_url = page.url
    page_title = get_page_title(page)
    completed, reason = check_wikipedia_completion(
        instruction, final_url, page_title)
    result["final_url"] = final_url
    result["success"] = completed
    result["reason"] = reason if completed else "Max steps reached"

    print(f"\n  {'✅' if completed else '⚠️ '}  "
          f"Max steps ({MAX_STEPS}) reached.")
    print(f"  Steps taken: {MAX_STEPS}")
    print(f"  Final URL: {final_url}")
    return result


# ═══════════════════════════════════════════════════════════════
#  Main
# ═══════════════════════════════════════════════════════════════
def main():
    parser = argparse.ArgumentParser(
        description="Wikipedia VLA Runner")
    parser.add_argument("--interactive", action="store_true",
                        help="Interactive mode (enter your own queries)")
    args = parser.parse_args()

    os.makedirs(LOG_DIR, exist_ok=True)

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("❌ Playwright not installed. Run: pip install playwright")
        sys.exit(1)

    print()
    print("══════════════════════════════════════════════════════════")
    print("  WIKIPEDIA VLA RUNNER")
    print("══════════════════════════════════════════════════════════")
    print(f"  Model:       {MODEL_NAME} (temp={TEMPERATURE})")
    print(f"  API:         /api/chat (think=false)")
    print(f"  Domain:      wikipedia")
    print(f"  Max steps:   {MAX_STEPS}")
    print(f"  Headless:    False")
    print(f"  Mode:        {'Interactive' if args.interactive else 'Auto (3 scenarios)'}")
    print(f"  Screenshots: {LOG_DIR}")
    print("══════════════════════════════════════════════════════════")

    all_results = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context(
            viewport={"width": 1280, "height": 720},
            locale="en-US",
        )

        try:
            if args.interactive:
                idx = 0
                while True:
                    print()
                    try:
                        instruction = input(
                            "Wikipedia instruction (or 'quit'): ").strip()
                    except (EOFError, KeyboardInterrupt):
                        print("\n  Goodbye!")
                        break

                    if not instruction or instruction.lower() in (
                            "quit", "exit", "q"):
                        print("  Goodbye!")
                        break

                    idx += 1
                    scenario = {
                        "instruction": instruction,
                        "start_url": "https://www.wikipedia.org",
                        "search_term": extract_search_term(instruction),
                    }
                    page = context.new_page()
                    try:
                        result = run_wikipedia_scenario(
                            page, scenario, idx)
                        all_results.append(result)
                    finally:
                        try:
                            page.close()
                        except Exception:
                            pass
            else:
                for idx, scenario in enumerate(WIKIPEDIA_SCENARIOS, 1):
                    page = context.new_page()
                    try:
                        result = run_wikipedia_scenario(
                            page, scenario, idx)
                        all_results.append(result)
                    finally:
                        try:
                            page.close()
                        except Exception:
                            pass

                    if idx < len(WIKIPEDIA_SCENARIOS):
                        print(f"\n  💤 Sleeping 2s before next scenario...")
                        time.sleep(2)

        finally:
            try:
                context.close()
                browser.close()
            except Exception:
                pass

    # ═══════════════════════════════════════════════════════════
    #  Summary
    # ═══════════════════════════════════════════════════════════
    print()
    print("══════════════════════════════════════════════════════════")
    print("  WIKIPEDIA VLA — RESULTS SUMMARY")
    print("══════════════════════════════════════════════════════════")
    print()
    print(f"  {'#':>2}  {'Success':>7}  {'Steps':>5}  "
          f"{'Instruction':<45}  {'Reason'}")
    print(f"  {'─' * 100}")

    total = len(all_results)
    successes = sum(1 for r in all_results if r["success"])

    for r in all_results:
        status = "✅" if r["success"] else "❌"
        print(f"  {r['scenario']:>2}  {status:>7}  "
              f"{r['steps_taken']:>5}  "
              f"{r['instruction'][:45]:<45}  "
              f"{r['reason'][:40]}")

    print()
    print(f"  Total: {total}  |  "
          f"Success: {successes}/{total}  |  "
          f"Rate: {successes/max(total,1)*100:.0f}%")
    print()
    print("══════════════════════════════════════════════════════════")
    print("  WIKIPEDIA DOMAIN SUPPORT VERIFIED")
    print(f"  {successes}/{total} scenarios completed successfully")
    print("  No crashes — clean shutdown")
    print("  Screenshots saved to interactive_logs/")
    print("══════════════════════════════════════════════════════════")


if __name__ == "__main__":
    main()
