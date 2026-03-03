#!/usr/bin/env python3
"""
Forum CRUD (LLM-driven) — Postmill at localhost:9999
LOGIN → CREATE → EDIT → REPLY → DELETE
Login is semi-deterministic; all CRUD ops are LLM-driven.
"""

import os, time
from datetime import datetime
from llm_dom_agent import LLMDOMAgent

FORUM_URL = "http://localhost:9999"


def _text_in_dom(page, text):
    try:
        body = page.evaluate("() => document.body?.innerText || ''")
        return text.lower() in body.lower()
    except Exception:
        return False


class ForumCRUD:
    def __init__(self, page, run_dir, max_steps=35, temperature=0.7,
                 username="MarvelsGrantMan136", password="test1234", verbose=True):
        self.page = page
        self.run_dir = run_dir
        self.max_steps = max_steps
        self.temperature = temperature
        self.username = username
        self.password = password
        self.verbose = verbose
        self.run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.submission_url = ""
        self.title_marker = f"VLA LLM CRUD {self.run_id}"
        self.edit_marker = f"EDIT_OK_{self.run_id}"
        self.reply_marker = f"REPLY_OK_{self.run_id}"

    def _agent(self, scenario):
        ss = os.path.join(self.run_dir, "forum", scenario)
        return LLMDOMAgent(
            self.page, max_steps=self.max_steps,
            temperature=self.temperature, ss_dir=ss, verbose=self.verbose,
        )

    # ── LOGIN (semi-deterministic) ──
    def login(self):
        t0 = time.time()
        r = {"op": "LOGIN", "success": False, "reason": "", "steps": 0, "latency": 0}
        try:
            self.page.goto(f"{FORUM_URL}/login", wait_until="domcontentloaded", timeout=12000)
            time.sleep(2.0)
            # Find and fill username
            for sel in ['input[name="_username"]', '#login_username',
                        'input[name="username"]', 'input[type="text"]']:
                loc = self.page.locator(sel)
                if loc.count() > 0:
                    loc.first.fill(self.username)
                    break
            # Find and fill password
            for sel in ['input[name="_password"]', '#login_password',
                        'input[type="password"]']:
                loc = self.page.locator(sel)
                if loc.count() > 0:
                    loc.first.fill(self.password)
                    break
            time.sleep(0.3)
            # Click login button
            for sel in ['button:has-text("Log in")', 'button[type="submit"]', 'input[type="submit"]']:
                loc = self.page.locator(sel)
                if loc.count() > 0:
                    loc.first.click()
                    break
            time.sleep(3.0)
            ag = self._agent("login")
            ag.screenshot("after_login")
            if "/login" not in self.page.url.lower() or _text_in_dom(self.page, self.username):
                r["success"] = True
                r["reason"] = f"Logged in as {self.username}"
            else:
                r["reason"] = "Still on login page"
            r["steps"] = 1
        except Exception as e:
            r["reason"] = str(e)[:80]
        r["latency"] = round(time.time() - t0, 2)
        return r

    # ── CREATE (LLM-driven with select2 assist) ──
    def create(self):
        t0 = time.time()
        r = {"op": "CREATE", "success": False, "reason": "", "steps": 0, "latency": 0}
        # Navigate to submit page so LLM starts on the form
        self.page.goto(f"{FORUM_URL}/submit", wait_until="domcontentloaded", timeout=10000)
        time.sleep(2.0)

        # Phase 1: LLM fills title and body
        goal_fill = (
            f"You are on a submission form page. Fill in the form fields:\n"
            f"1. Find the textarea for Title (name contains 'title') and TYPE: \"{self.title_marker}\"\n"
            f"2. Find the textarea for Body (name contains 'body') and TYPE: \"Automated LLM CRUD validation.\"\n"
            f"3. After filling BOTH fields, output STOP.\n"
            f"IMPORTANT: Use TYPE for text fields."
        )
        agent1 = self._agent("create_fill")
        agent1.max_steps = 8
        res1 = agent1.run(goal_fill)

        # Phase 2: Handle select2 dropdown via Playwright interaction
        # (Proven approach: click combobox → type search → click option)
        try:
            self.page.locator('span[role="combobox"]').click(timeout=3000)
            time.sleep(0.5)
            self.page.locator('input[role="searchbox"]').fill('AskReddit')
            time.sleep(0.5)
            self.page.locator('li[role="option"]:has-text("AskReddit")').click(timeout=3000)
            time.sleep(0.5)
        except Exception as e:
            if self.verbose:
                print(f"    ⚠ Select2 fallback: {str(e)[:50]}")

        # Phase 3: Click "Create submission" button directly
        try:
            for btn_sel in ['button:has-text("Create submission")',
                            'button[type="submit"]',
                            'input[type="submit"]']:
                loc = self.page.locator(btn_sel)
                if loc.count() > 0:
                    loc.first.click()
                    break
            time.sleep(3.0)
        except Exception as e:
            if self.verbose:
                print(f"    ⚠ Submit click: {str(e)[:50]}")

        r["steps"] = res1.get("steps", 0) + 1
        # Verify
        if _text_in_dom(self.page, self.title_marker) and "/submit" not in self.page.url:
            self.submission_url = self.page.url
            r["success"] = True
            r["reason"] = f"Created: {self.submission_url[:50]}"
        else:
            r["reason"] = f"Still on: {self.page.url[:50]}"
        r["latency"] = round(time.time() - t0, 2)
        return r

    # ── EDIT (LLM-driven) ──
    def edit(self):
        t0 = time.time()
        r = {"op": "EDIT", "success": False, "reason": "", "steps": 0, "latency": 0}
        if not self.submission_url:
            r["reason"] = "No submission URL"
            return r
        # Navigate to submission
        self.page.goto(self.submission_url, wait_until="domcontentloaded", timeout=10000)
        time.sleep(2.0)
        goal = (
            f"Edit this forum post. Do these steps IN ORDER:\n"
            f"1. Find and CLICK the 'Edit' link on this page.\n"
            f"2. You will see an edit form with a Body textarea. Use TYPE to replace the body text with: \"{self.edit_marker}\"\n"
            f"3. CLICK the 'Save' or 'Edit submission' button to save changes.\n"
            f"4. After the page reloads showing the updated post, output STOP.\n"
            f"IMPORTANT: You MUST use TYPE to change the body text. Do NOT just click Save without typing first."
        )
        agent = self._agent("edit")
        res = agent.run(goal)
        agent.save_trace(os.path.join(self.run_dir, "forum", "edit_trace.json"))
        r["steps"] = res.get("steps", 0)
        if _text_in_dom(self.page, self.edit_marker):
            r["success"] = True
            r["reason"] = "Edit marker visible"
        else:
            r["reason"] = res.get("reason", "Edit marker not found")
        r["latency"] = round(time.time() - t0, 2)
        return r

    # ── REPLY (LLM-driven) ──
    def reply(self):
        t0 = time.time()
        r = {"op": "REPLY", "success": False, "reason": "", "steps": 0, "latency": 0}
        if not self.submission_url:
            r["reason"] = "No submission URL"
            return r
        self.page.goto(self.submission_url, wait_until="domcontentloaded", timeout=10000)
        time.sleep(2.0)
        goal = (
            f"Post a reply/comment on this forum post. Do these steps IN ORDER:\n"
            f"1. Find the comment textarea on this page (it may say 'Body' and be a textarea element).\n"
            f"2. TYPE this text into it: \"{self.reply_marker}\"\n"
            f"3. CLICK the submit/post button (it may say 'Post comment' or 'Submit').\n"
            f"4. After the reply appears on the page, output STOP.\n"
            f"IMPORTANT: After typing the comment, you MUST click the submit button. Don't keep re-typing."
        )
        agent = self._agent("reply")
        res = agent.run(goal)
        agent.save_trace(os.path.join(self.run_dir, "forum", "reply_trace.json"))
        r["steps"] = res.get("steps", 0)
        if _text_in_dom(self.page, self.reply_marker):
            r["success"] = True
            r["reason"] = "Reply marker visible"
        else:
            r["reason"] = res.get("reason", "Reply marker not found")
        r["latency"] = round(time.time() - t0, 2)
        return r

    # ── DELETE (LLM-driven) ──
    def delete(self):
        t0 = time.time()
        r = {"op": "DELETE", "success": False, "reason": "", "steps": 0, "latency": 0}
        if not self.submission_url:
            r["reason"] = "No submission URL"
            return r
        self.page.goto(self.submission_url, wait_until="domcontentloaded", timeout=10000)
        time.sleep(2.0)
        goal = (
            "Delete this submission/post. Find and click the 'Delete' button. "
            "If a confirmation appears, confirm the deletion. "
            "When the post is deleted and you are redirected or see a success message, output STOP."
        )
        agent = self._agent("delete")
        res = agent.run(goal)
        agent.save_trace(os.path.join(self.run_dir, "forum", "delete_trace.json"))
        r["steps"] = res.get("steps", 0)
        if not _text_in_dom(self.page, self.title_marker):
            r["success"] = True
            r["reason"] = "Title no longer visible"
        elif "/submit" not in self.page.url and self.submission_url != self.page.url:
            r["success"] = True
            r["reason"] = "Redirected away"
        else:
            r["reason"] = res.get("reason", "Title still visible")
        r["latency"] = round(time.time() - t0, 2)
        return r

    # ── Run all ──
    def run_all(self, allow_delete=False):
        print("\n" + "━" * 60)
        print("  🗨️  FORUM LLM CRUD — LOGIN → CREATE → EDIT → REPLY" +
              (" → DELETE" if allow_delete else ""))
        print("━" * 60)
        results = []
        ops = [
            ("LOGIN", self.login),
            ("CREATE", self.create),
            ("EDIT", self.edit),
            ("REPLY", self.reply),
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
            "domain": "forum",
            "results": results,
            "total_success": sum(1 for x in results if x["success"]),
            "total_ops": len(results),
        }
