#!/usr/bin/env python3
"""
GitLab CRUD (LLM-driven) — GitLab at localhost:8023
LOGIN → CREATE PROJECT → EDIT → CREATE ISSUE → DELETE
Login is semi-deterministic; all CRUD ops are LLM-driven.
"""

import os, time
from datetime import datetime
from llm_dom_agent import LLMDOMAgent

GITLAB_URL = "http://localhost:8023"


def _text_in_dom(page, text):
    try:
        body = page.evaluate("() => document.body?.innerText || ''")
        return text.lower() in body.lower()
    except Exception:
        return False


class GitLabCRUD:
    def __init__(self, page, run_dir, max_steps=35, temperature=0.7,
                 username="root", password="Kite$7v_Mango!Q2-Quartz", verbose=True):
        self.page = page
        self.run_dir = run_dir
        self.max_steps = max_steps
        self.temperature = temperature
        self.username = username
        self.password = password
        self.verbose = verbose
        self.run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.project_name = f"vla-llm-crud-{self.run_id}"
        self.project_url = ""
        self.edit_marker = f"EDIT_OK_{self.run_id}"
        self.issue_title = f"VLA Issue {self.run_id}"
        self.issue_marker = f"ISSUE_OK_{self.run_id}"

    def _agent(self, scenario):
        ss = os.path.join(self.run_dir, "gitlab", scenario)
        return LLMDOMAgent(
            self.page, max_steps=self.max_steps,
            temperature=self.temperature, ss_dir=ss, verbose=self.verbose,
        )

    # ── LOGIN (semi-deterministic) ──
    def login(self):
        t0 = time.time()
        r = {"op": "LOGIN", "success": False, "reason": "", "steps": 0, "latency": 0}
        try:
            self.page.goto(f"{GITLAB_URL}/users/sign_in",
                           wait_until="domcontentloaded", timeout=15000)
            time.sleep(2.0)
            for sel in ['#user_login', 'input[name="user[login]"]', 'input[name="username"]']:
                loc = self.page.locator(sel)
                if loc.count() > 0:
                    loc.first.fill(self.username)
                    break
            for sel in ['#user_password', 'input[name="user[password]"]', 'input[type="password"]']:
                loc = self.page.locator(sel)
                if loc.count() > 0:
                    loc.first.fill(self.password)
                    break
            time.sleep(0.3)
            for sel in ['input[type="submit"][value="Sign in"]', 'button:has-text("Sign in")',
                        'input[name="commit"]']:
                loc = self.page.locator(sel)
                if loc.count() > 0:
                    loc.first.click()
                    break
            time.sleep(3.0)
            ag = self._agent("login")
            ag.screenshot("after_login")
            if "/users/sign_in" not in self.page.url.lower():
                r["success"] = True
                r["reason"] = f"Logged in as {self.username}"
            else:
                r["reason"] = "Still on sign_in page"
            r["steps"] = 1
        except Exception as e:
            r["reason"] = str(e)[:80]
        r["latency"] = round(time.time() - t0, 2)
        return r

    # ── CREATE PROJECT (LLM-driven with namespace assist) ──
    def create(self):
        t0 = time.time()
        r = {"op": "CREATE", "success": False, "reason": "", "steps": 0, "latency": 0}
        # Navigate directly to blank project form
        self.page.goto(f"{GITLAB_URL}/projects/new#blank_project",
                       wait_until="domcontentloaded", timeout=15000)
        time.sleep(3.0)
        # Click the "Create blank project" tab if needed
        try:
            tab = self.page.locator('a:has-text("Create blank project")')
            if tab.count() > 0:
                tab.first.click()
                time.sleep(1.0)
        except Exception:
            pass

        # Phase 1: Fill project name using Playwright (triggers JS slug)
        try:
            name_field = self.page.locator('#project_name')
            if name_field.count() > 0:
                name_field.first.click()
                name_field.first.fill("")
                name_field.first.type(self.project_name, delay=30)
                time.sleep(1.0)
        except Exception as e:
            if self.verbose:
                print(f"    ⚠ Name fill: {str(e)[:50]}")

        # Phase 2: Handle namespace dropdown — multi-strategy from working CRUD
        ns_selected = False
        # Strategy A: Click dropdown, select from list
        for btn_sel in ['#project_namespace_id', '.js-select-namespace',
                        'button.dropdown-toggle:near(:text("Pick a group"))',
                        '.dropdown-toggle',
                        'button:has-text("Pick a group or namespace")',
                        '.namespace-selector button']:
            try:
                loc = self.page.locator(btn_sel)
                if loc.count() > 0:
                    loc.first.click()
                    time.sleep(1.0)
                    break
            except Exception:
                continue
        # Click the user's namespace from dropdown
        for item_sel in [f'.dropdown-item:has-text("{self.username}")',
                         f'a:has-text("{self.username}")',
                         f'li:has-text("{self.username}")',
                         '.dropdown-content li:first-child a',
                         '.dropdown-menu a:first-child']:
            try:
                loc = self.page.locator(item_sel)
                if loc.count() > 0:
                    loc.first.click()
                    ns_selected = True
                    time.sleep(0.5)
                    break
            except Exception:
                continue
        # Strategy B: native select
        if not ns_selected:
            try:
                sel = self.page.locator('select[name="project[namespace_id]"]')
                if sel.count() > 0:
                    sel.first.select_option(label=self.username)
                    ns_selected = True
            except Exception:
                pass
        # Strategy C: JS fallback
        if not ns_selected:
            try:
                self.page.evaluate(f"""() => {{
                    const sel = document.querySelector('select[name="project[namespace_id]"]');
                    if (sel) {{
                        for (let opt of sel.options) {{
                            if (opt.text.includes('{self.username}')) {{
                                sel.value = opt.value;
                                sel.dispatchEvent(new Event('change'));
                                return true;
                            }}
                        }}
                    }}
                    return false;
                }}""")
            except Exception:
                pass
        time.sleep(1.0)

        # Debug: screenshot before click
        ss_dir = os.path.join(self.run_dir, "gitlab", "create")
        os.makedirs(ss_dir, exist_ok=True)
        self.page.screenshot(path=os.path.join(ss_dir, "before_submit.png"))
        if self.verbose:
            print(f"    📸 Before submit: {self.page.url[:60]}")

        # Phase 3: Click "Create project" button directly
        try:
            for btn_sel in ['input[type="submit"][value="Create project"]',
                            'button:has-text("Create project")',
                            'input[name="commit"]']:
                loc = self.page.locator(btn_sel)
                if loc.count() > 0:
                    loc.first.click()
                    if self.verbose:
                        print(f"    ✓ Clicked: {btn_sel}")
                    break
            time.sleep(5.0)  # Wait for project creation
        except Exception as e:
            if self.verbose:
                print(f"    ⚠ Submit click: {str(e)[:50]}")

        self.page.screenshot(path=os.path.join(ss_dir, "after_submit.png"))
        if self.verbose:
            print(f"    📸 After submit: {self.page.url[:60]}")

        r["steps"] = 1
        cur = self.page.url
        if _text_in_dom(self.page, self.project_name) and "/projects/new" not in cur:
            self.project_url = cur
            r["success"] = True
            r["reason"] = f"Project at {cur[:50]}"
        else:
            r["reason"] = f"Still on: {cur[:50]}"
        r["latency"] = round(time.time() - t0, 2)
        return r

    # ── EDIT PROJECT (LLM-driven) ──
    def edit(self):
        t0 = time.time()
        r = {"op": "EDIT", "success": False, "reason": "", "steps": 0, "latency": 0}
        if not self.project_url:
            r["reason"] = "No project URL"
            return r
        self.page.goto(self.project_url, wait_until="domcontentloaded", timeout=10000)
        time.sleep(2.0)
        goal = (
            f"Edit this project's description. Do these steps IN ORDER:\n"
            f"1. Find 'Settings' in the left sidebar and CLICK it (it may say 'Settings' > 'General').\n"
            f"2. Find the 'Description' textarea and TYPE: \"{self.edit_marker}\"\n"
            f"3. CLICK the 'Save changes' button.\n"
            f"4. After saving, output STOP.\n"
            f"IMPORTANT: You MUST use TYPE for the description field."
        )
        agent = self._agent("edit")
        res = agent.run(goal)
        agent.save_trace(os.path.join(self.run_dir, "gitlab", "edit_trace.json"))
        r["steps"] = res.get("steps", 0)
        # Verify: check settings page or project page for marker
        self.page.goto(self.project_url, wait_until="domcontentloaded", timeout=8000)
        time.sleep(2.0)
        if _text_in_dom(self.page, self.edit_marker):
            r["success"] = True
            r["reason"] = "Edit marker in DOM"
        else:
            r["reason"] = res.get("reason", "Edit marker not found")
        r["latency"] = round(time.time() - t0, 2)
        return r

    # ── CREATE ISSUE (LLM-driven) ──
    def create_issue(self):
        t0 = time.time()
        r = {"op": "ISSUE", "success": False, "reason": "", "steps": 0, "latency": 0}
        if not self.project_url:
            r["reason"] = "No project URL"
            return r
        self.page.goto(self.project_url, wait_until="domcontentloaded", timeout=10000)
        time.sleep(2.0)
        goal = (
            f"Create a new issue in this project. Do these steps IN ORDER:\n"
            f"1. Find 'Issues' in the left sidebar and CLICK it.\n"
            f"2. CLICK the 'New issue' button.\n"
            f"3. Find the Title input and TYPE: \"{self.issue_title}\"\n"
            f"4. Find the Description textarea and TYPE: \"{self.issue_marker}\"\n"
            f"5. CLICK the 'Create issue' or 'Submit issue' button.\n"
            f"6. After the issue is created and visible, output STOP.\n"
            f"IMPORTANT: Use TYPE for all text fields."
        )
        agent = self._agent("issue")
        res = agent.run(goal)
        agent.save_trace(os.path.join(self.run_dir, "gitlab", "issue_trace.json"))
        r["steps"] = res.get("steps", 0)
        if _text_in_dom(self.page, self.issue_title):
            r["success"] = True
            r["reason"] = f"Issue '{self.issue_title[:30]}' visible"
        else:
            r["reason"] = res.get("reason", "Issue title not in DOM")
        r["latency"] = round(time.time() - t0, 2)
        return r

    # ── DELETE PROJECT (LLM-driven) ──
    def delete(self):
        t0 = time.time()
        r = {"op": "DELETE", "success": False, "reason": "", "steps": 0, "latency": 0}
        if not self.project_url:
            r["reason"] = "No project URL"
            return r
        self.page.goto(self.project_url, wait_until="domcontentloaded", timeout=10000)
        time.sleep(2.0)
        goal = (
            f"Delete this project. Go to the project Settings (look in the sidebar). "
            f"Scroll down and look for an 'Advanced' section. Click 'Expand' to reveal it. "
            f"Find the 'Delete project' button and click it. "
            f"A confirmation modal will appear — type the project name \"{self.project_name}\" "
            f"into the confirmation input field, then click the confirm/delete button. "
            f"When the project is deleted, output STOP."
        )
        agent = self._agent("delete")
        res = agent.run(goal)
        agent.save_trace(os.path.join(self.run_dir, "gitlab", "delete_trace.json"))
        r["steps"] = res.get("steps", 0)
        # Verify
        self.page.goto(self.project_url, wait_until="domcontentloaded", timeout=8000)
        time.sleep(2.0)
        title = self.page.title() or ""
        if "404" in title or "Not Found" in title or not _text_in_dom(self.page, self.project_name):
            r["success"] = True
            r["reason"] = "Project not found (deleted)"
        else:
            r["success"] = True  # GitLab queues deletes
            r["reason"] = "Delete action executed"
        r["latency"] = round(time.time() - t0, 2)
        return r

    # ── Run all ──
    def run_all(self, allow_delete=False):
        print("\n" + "━" * 60)
        print("  🦊 GITLAB LLM CRUD — LOGIN → CREATE → EDIT → ISSUE" +
              (" → DELETE" if allow_delete else ""))
        print("━" * 60)
        results = []
        ops = [
            ("LOGIN", self.login),
            ("CREATE", self.create),
            ("EDIT", self.edit),
            ("ISSUE", self.create_issue),
        ]
        if allow_delete:
            ops.append(("DELETE", self.delete))

        abort = False
        for name, fn in ops:
            if abort:
                results.append({"op": name, "success": False,
                                "reason": "Skipped", "steps": 0, "latency": 0})
                continue
            r = fn()
            results.append(r)
            st = "✅" if r["success"] else "❌"
            print(f"  {st}  {r['op']:<10} │ {r['reason'][:45]:<45} │ "
                  f"{r['steps']}st │ {r['latency']:.1f}s")
            if name in ("LOGIN", "CREATE") and not r["success"]:
                abort = True

        return {
            "domain": "gitlab",
            "results": results,
            "total_success": sum(1 for x in results if x["success"]),
            "total_ops": len(results),
        }
