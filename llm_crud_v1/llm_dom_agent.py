#!/usr/bin/env python3
"""
LLM DOM Agent — Generic LLM-driven browser automation via DOM extraction.

- Extracts visible interactive elements with JS
- Injects data-vla-id for stable targeting
- Calls Ollama /api/chat (think:false)
- Supports CLICK, TYPE, STOP actions
"""

import json, os, re, time, urllib.request
from datetime import datetime

DOM_EXTRACT_JS = """
() => {
    document.querySelectorAll('[data-vla-id]').forEach(el => el.removeAttribute('data-vla-id'));
    const sels = 'a, button, input, textarea, select, [role="button"], [role="link"], ' +
                 '[role="menuitem"], [role="tab"], [role="checkbox"], [role="radio"], ' +
                 '[role="combobox"], [role="option"], [contenteditable="true"]';
    const els = document.querySelectorAll(sels);
    const res = []; let id = 1;
    for (const el of els) {
        const r = el.getBoundingClientRect();
        const s = window.getComputedStyle(el);
        if (r.width === 0 && r.height === 0) continue;
        if (s.display === 'none' || s.visibility === 'hidden' || s.opacity === '0') continue;
        if (r.bottom < -50 || r.top > window.innerHeight * 3) continue;
        if (el.disabled) continue;
        if (el.tagName === 'OPTION') continue;
        // Skip native select hidden by select2
        if (el.tagName === 'SELECT') {
            const next = el.nextElementSibling;
            if (next && (next.classList.contains('select2') || next.classList.contains('select2-container')
                || next.querySelector('[role=\"combobox\"]'))) continue;
            if (r.height < 5) continue;
        }
        let txt = '';
        if (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA') {
            txt = el.value || '';
        } else if (el.tagName === 'SELECT') {
            const o = el.options[el.selectedIndex];
            txt = o ? o.text : '';
        } else {
            txt = (el.innerText || el.textContent || '').trim();
        }
        if (txt.length > 80) txt = txt.substring(0, 77) + '...';
        txt = txt.replace(/\\s+/g, ' ').trim();
        const tag = el.tagName.toLowerCase();
        const role = el.getAttribute('role') || '';
        const tp = el.getAttribute('type') || '';
        const nm = el.getAttribute('name') || '';
        const ph = el.getAttribute('placeholder') || '';
        const ar = el.getAttribute('aria-label') || '';
        const hr = el.getAttribute('href') || '';
        const ti = el.getAttribute('title') || '';
        el.setAttribute('data-vla-id', String(id));
        let d = '[' + id + '] ' + tag;
        if (role) d += '(' + role + ')';
        if (tp) d += ' type=' + tp;
        if (txt) d += ' "' + txt + '"';
        else if (ar) d += ' aria="' + ar + '"';
        else if (ph) d += ' ph="' + ph + '"';
        else if (ti) d += ' title="' + ti + '"';
        else if (nm) d += ' name=' + nm;
        if (hr && tag === 'a') {
            let sh = hr;
            if (sh.length > 40) sh = '...' + sh.slice(-37);
            d += ' -> ' + sh;
        }
        res.push({id:id, tag:tag, role:role, type:tp, text:txt,
                  name:nm, placeholder:ph, ariaLabel:ar, href:hr, desc:d});
        id++;
        if (id > 120) break;
    }
    return res;
}
"""

SYSTEM_PROMPT = (
    "You are a web browser automation agent. You see interactive elements on a page, "
    "each with an ID number. Accomplish the given goal by picking elements to click or type into.\n"
    "Rules:\n"
    "- Reply with exactly ONE action per response:\n"
    "  CLICK <id>  — click a link, button, or interactive element\n"
    '  TYPE <id> "text"  — clear the field and type text into an input or textarea\n'
    "  STOP  — when the goal is fully achieved\n"
    "- IMPORTANT: When you see a form with input/textarea fields that need filling, "
    "use TYPE to fill them BEFORE clicking the submit button.\n"
    "- For dropdown/select elements, use CLICK to open them and then CLICK to select an option.\n"
    "- Do NOT keep clicking the same element repeatedly. If an action didn't change the page, try something different.\n"
    "- Be efficient and direct. Output ONLY the action line, no explanation."
)


class LLMDOMAgent:
    def __init__(self, page, ollama_url="http://localhost:11434",
                 model="qwen3:8b", temperature=0.7,
                 max_steps=35, ss_dir=None, verbose=True):
        self.page = page
        self.ollama_url = ollama_url
        self.model = model
        self.temperature = temperature
        self.max_steps = max_steps
        self.ss_dir = ss_dir
        self.verbose = verbose
        self.action_history = []
        self.trace = []
        self.step_count = 0

    def screenshot(self, name):
        if not self.ss_dir:
            return None
        os.makedirs(self.ss_dir, exist_ok=True)
        p = os.path.join(self.ss_dir, f"{name}.png")
        try:
            self.page.screenshot(path=p)
        except Exception:
            pass
        return p

    def extract_dom(self):
        try:
            return self.page.evaluate(DOM_EXTRACT_JS) or []
        except Exception as e:
            if self.verbose:
                print(f"    ⚠ DOM extract error: {e}")
            return []

    def _build_obs(self, elements, goal):
        url = self.page.url
        title = self.page.title() or ""
        # Get short visible text for context
        try:
            body_text = self.page.evaluate(
                "() => (document.body?.innerText || '').substring(0, 300)")
        except Exception:
            body_text = ""
        el_text = "\n".join(e["desc"] for e in elements[:100])
        recent = self.action_history[-6:]
        mem = "\n".join(f"  {a}" for a in recent) if recent else "  (none)"
        return (
            f"URL: {url}\nTitle: {title}\n\nGoal: {goal}\n\n"
            f"Page text (first 300 chars): {body_text[:300]}\n\n"
            f"Recent actions:\n{mem}\n\n"
            f"Interactive elements on page:\n{el_text}\n\n"
            f"Pick the next action (CLICK <id>, TYPE <id> \"text\", or STOP):"
        )

    def call_llm(self, system_prompt, user_prompt):
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "stream": False,
            "options": {"temperature": self.temperature},
            "think": False,
        }
        data = json.dumps(payload).encode()
        req = urllib.request.Request(
            f"{self.ollama_url}/api/chat", data=data,
            headers={"Content-Type": "application/json"}, method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=90) as resp:
                body = json.loads(resp.read().decode())
                return body.get("message", {}).get("content", "").strip()
        except Exception as e:
            if self.verbose:
                print(f"    ⚠ LLM error: {e}")
            return "STOP"

    def _parse(self, resp):
        line = resp.strip().split("\n")[0].strip()
        # Remove markdown backticks if present
        line = re.sub(r'^```\w*\s*', '', line).rstrip('`').strip()
        m = re.match(r"CLICK\s+\[?(\d+)\]?", line, re.I)
        if m:
            return ("CLICK", int(m.group(1)), "")
        m = re.match(r'TYPE\s+\[?(\d+)\]?\s+"(.*?)"', line, re.I)
        if m:
            return ("TYPE", int(m.group(1)), m.group(2))
        m = re.match(r"TYPE\s+\[?(\d+)\]?\s+'(.*?)'", line, re.I)
        if m:
            return ("TYPE", int(m.group(1)), m.group(2))
        if re.search(r"\bSTOP\b", line, re.I):
            return ("STOP", 0, "")
        return ("UNKNOWN", 0, line)

    def _is_search(self, el):
        hints = ["search", "query", "find", "filter"]
        for f in [el.get("name",""), el.get("placeholder",""),
                  el.get("ariaLabel",""), el.get("type","")]:
            if any(h in f.lower() for h in hints):
                return True
        return False

    def _exec(self, atype, aid, atext, elements):
        if atype == "STOP":
            return "STOP"
        if atype == "UNKNOWN":
            return f"Unknown: {atext[:40]}"
        sel = f'[data-vla-id="{aid}"]'
        try:
            loc = self.page.locator(sel)
            if loc.count() == 0:
                return f"Element {aid} not found"
            if atype == "CLICK":
                loc.first.scroll_into_view_if_needed(timeout=3000)
                loc.first.click(timeout=5000)
                time.sleep(1.0)
                return f"Clicked {aid}"
            elif atype == "TYPE":
                el_info = next((e for e in elements if e["id"] == aid), None)
                loc.first.scroll_into_view_if_needed(timeout=3000)
                loc.first.click(timeout=3000)
                time.sleep(0.15)
                loc.first.fill(atext)
                time.sleep(0.3)
                if el_info and self._is_search(el_info):
                    loc.first.press("Enter")
                    time.sleep(1.0)
                return f"Typed into {aid}"
        except Exception as e:
            return f"Error {atype} {aid}: {str(e)[:50]}"

    def run(self, goal, system_prompt=None):
        if system_prompt is None:
            system_prompt = SYSTEM_PROMPT
        self.action_history = []
        self.trace = []
        self.step_count = 0
        same_url_count = 0
        last_url = ""
        result = {"success": False, "reason": "max steps", "steps": 0}

        for step in range(1, self.max_steps + 1):
            self.step_count = step
            cur_url = self.page.url
            if cur_url == last_url:
                same_url_count += 1
            else:
                same_url_count = 0
            last_url = cur_url
            if same_url_count >= 12:
                result["reason"] = "URL loop (12 same-URL steps)"
                break

            self.screenshot(f"step_{step:02d}")
            elements = self.extract_dom()
            if self.verbose:
                print(f"  Step {step}/{self.max_steps} | {cur_url[:55]} | {len(elements)} els")

            obs = self._build_obs(elements, goal)
            # Detect repetition: if last 3 actions identical, add warning
            if len(self.action_history) >= 3:
                last3 = [a.split(": ", 1)[-1] for a in self.action_history[-3:]]
                if len(set(last3)) == 1:
                    obs += (
                        f"\n\nWARNING: You have repeated the action '{last3[0]}' "
                        f"three times. This is NOT working. Try a DIFFERENT action. "
                        f"If you need to fill a field, use TYPE. If you need to "
                        f"submit, find and CLICK the submit button."
                    )
            t0 = time.time()
            resp = self.call_llm(system_prompt, obs)
            lt = round(time.time() - t0, 2)

            atype, aid, atext = self._parse(resp)
            astr = f"{atype} {aid}" + (f' "{atext}"' if atext else "")
            if self.verbose:
                print(f"    → {astr} ({lt}s)")

            rec = f"Step {step}: {astr}"
            self.action_history.append(rec)
            entry = {"step": step, "url": cur_url, "els": len(elements),
                     "llm": resp[:120], "action": astr, "llm_time": lt}

            if atype == "STOP":
                entry["result"] = "STOP"
                self.trace.append(entry)
                result = {"success": True, "reason": "STOP", "steps": step}
                break

            ex = self._exec(atype, aid, atext, elements)
            entry["result"] = ex
            self.trace.append(entry)
            if self.verbose:
                print(f"    ✓ {ex[:55]}")

            time.sleep(0.4)
            try:
                self.page.wait_for_load_state("domcontentloaded", timeout=5000)
            except Exception:
                pass

        result["steps"] = self.step_count
        result["trace"] = self.trace
        return result

    def save_trace(self, path):
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w") as f:
            json.dump(self.trace, f, indent=2)
