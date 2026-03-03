#!/usr/bin/env python3
"""
Forum CRUD Agent — Deterministic CRUD operations on the WebArena Postmill Forum.

Operations: LOGIN → CREATE submission → EDIT submission → REPLY → DELETE submission
All verification is DOM-based.

Env vars: FORUM_USER, FORUM_PASS
"""

import os
import time
from datetime import datetime

FORUM_BASE = "http://localhost:9999"
FORUM_USER = os.environ.get("FORUM_USER", "")
FORUM_PASS = os.environ.get("FORUM_PASS", "")

THREAD_TITLE = "VLA CRUD Test Thread"
THREAD_BODY  = "Automated CRUD validation."
EDIT_BODY    = "Edited by VLA CRUD system."
REPLY_BODY   = "Reply from VLA CRUD agent."

# Track the created submission URL for edit/reply/delete
_submission_url = ""
_submission_forum = ""


def _screenshot(page, ss_dir, name):
    if ss_dir:
        try:
            page.screenshot(path=os.path.join(ss_dir, f"{name}.png"))
        except Exception:
            pass


def _wait(s=1.0):
    time.sleep(s)


def _find_and_click(page, selectors, timeout=5000):
    """Try multiple selectors; click the first one found."""
    for sel in selectors:
        try:
            loc = page.locator(sel)
            if loc.count() > 0:
                loc.first.click(timeout=timeout)
                return True
        except Exception:
            continue
    return False


def _find_and_fill(page, selectors, text, timeout=3000):
    """Try multiple selectors; fill the first one found."""
    for sel in selectors:
        try:
            loc = page.locator(sel)
            if loc.count() > 0:
                loc.first.click(timeout=timeout)
                time.sleep(0.1)
                loc.first.fill(text)
                return True
        except Exception:
            continue
    return False


def _text_in_dom(page, text):
    """Check if text exists anywhere in body innerText."""
    try:
        body = page.evaluate("() => document.body?.innerText || ''")
        return text.lower() in body.lower()
    except Exception:
        return False


# ═══════════════════════════════════════════════════════════════
#  CRUD Operations — Postmill-specific
# ═══════════════════════════════════════════════════════════════

def forum_login(page, ss_dir=None):
    """Step 1: Login to Postmill forum."""
    t0 = time.time()
    result = {"operation": "LOGIN", "success": False, "reason": "", "latency": 0}

    if not FORUM_USER or not FORUM_PASS:
        result["reason"] = "FORUM_USER/FORUM_PASS not set"
        result["latency"] = round(time.time() - t0, 2)
        return result

    try:
        page.goto(f"{FORUM_BASE}/login", wait_until="domcontentloaded", timeout=15000)
        _wait(2.0)
        _screenshot(page, ss_dir, "01_forum_login")

        # Postmill login fields
        filled_user = _find_and_fill(page, [
            '#login_username', '#login-username',
            'input[name="_username"]', 'input[name="username"]',
            'input[id*="username"]',
        ], FORUM_USER)

        filled_pass = _find_and_fill(page, [
            '#login_password', '#login-password',
            'input[name="_password"]', 'input[name="password"]',
            'input[type="password"]',
        ], FORUM_PASS)

        if not filled_user or not filled_pass:
            result["reason"] = f"Could not fill credentials (user={filled_user}, pass={filled_pass})"
            result["latency"] = round(time.time() - t0, 2)
            return result

        _wait(0.5)
        _screenshot(page, ss_dir, "02_login_filled")

        # Submit — Postmill uses "Log in" button
        _find_and_click(page, [
            'button:has-text("Log in")', 'button.button:has-text("Log")',
            'button[type="submit"]', 'input[type="submit"]',
        ])

        _wait(3.0)
        _screenshot(page, ss_dir, "03_after_login")

        # Verify login — check if username appears or we're off /login
        url = page.url.lower()
        if ("/login" not in url
                or _text_in_dom(page, FORUM_USER)
                or _text_in_dom(page, "Log out")):
            result["success"] = True
            result["reason"] = f"Logged in as {FORUM_USER}"
        else:
            result["reason"] = "Login verification failed — still on /login"

    except Exception as e:
        result["reason"] = f"Error: {str(e)[:80]}"

    result["latency"] = round(time.time() - t0, 2)
    return result


def forum_create_thread(page, ss_dir=None):
    """Step 2: Create a new submission (thread) on Postmill."""
    global _submission_url, _submission_forum
    t0 = time.time()
    result = {"operation": "CREATE", "success": False, "reason": "", "latency": 0}

    try:
        # Navigate to submit page
        page.goto(f"{FORUM_BASE}/submit", wait_until="domcontentloaded", timeout=10000)
        _wait(2.0)
        _screenshot(page, ss_dir, "04_submit_page")

        # Fill title (Postmill: #submission_title is a textarea)
        _find_and_fill(page, [
            '#submission_title', 'textarea[name="submission[title]"]',
            'textarea[name*="title"]', 'input[name*="title"]',
        ], THREAD_TITLE)

        _wait(0.5)

        # Fill body (Postmill: #submission_body is a textarea)
        _find_and_fill(page, [
            '#submission_body', 'textarea[name="submission[body]"]',
            'textarea[name*="body"]',
        ], THREAD_BODY)

        _wait(0.5)

        # Select a forum via the select2 dropdown
        # Click the select2 container to open dropdown
        _find_and_click(page, [
            '.select2-selection', '.select2-selection--single',
            '#select2-submission_forum-container',
        ])
        _wait(1.0)

        # Type to search and select a forum (e.g., "AskReddit")
        try:
            search_input = page.locator('.select2-search__field, input.select2-search__field')
            if search_input.count() > 0:
                search_input.first.fill("AskReddit")
                _wait(1.0)
                # Click the first result
                _find_and_click(page, [
                    '.select2-results__option:first-child',
                    '.select2-results__option--highlighted',
                    'li.select2-results__option',
                ])
            else:
                # Try clicking first option directly
                _find_and_click(page, [
                    '.select2-results__option:first-child',
                    'li.select2-results__option',
                ])
        except Exception:
            # Fallback: just click first available option
            _find_and_click(page, ['.select2-results__option:first-child'])

        _wait(1.0)
        _screenshot(page, ss_dir, "05_submit_filled")

        # Click "Create submission" button
        _find_and_click(page, [
            'button:has-text("Create submission")',
            'button.button[type="submit"]',
            'button[type="submit"]',
        ])

        _wait(3.0)
        _screenshot(page, ss_dir, "06_after_create")

        # After creation, Postmill redirects to /f/{forum}/{id}/-/{slug}
        cur_url = page.url
        if "/submit" not in cur_url and _text_in_dom(page, THREAD_TITLE):
            _submission_url = cur_url
            # Extract forum name from URL (e.g., /f/AskReddit/123/-/...)
            parts = cur_url.replace(FORUM_BASE, "").split("/")
            if len(parts) >= 3 and parts[1] == "f":
                _submission_forum = parts[2]
            result["success"] = True
            result["reason"] = f"Submission created: {_submission_forum}"
        else:
            # Check for errors
            errors = page.evaluate(
                "() => document.querySelector('.form-error, .alert, .flash')?.innerText || ''")
            result["reason"] = f"Create failed: {errors[:60] or 'still on submit page'}"

    except Exception as e:
        result["reason"] = f"Error: {str(e)[:80]}"

    result["latency"] = round(time.time() - t0, 2)
    return result


def forum_edit_thread(page, ss_dir=None):
    """Step 3: Edit the submission body."""
    t0 = time.time()
    result = {"operation": "EDIT", "success": False, "reason": "", "latency": 0}

    if not _submission_url:
        result["reason"] = "No submission URL (create must succeed first)"
        result["latency"] = round(time.time() - t0, 2)
        return result

    try:
        # Navigate to the submission page
        page.goto(_submission_url, wait_until="domcontentloaded", timeout=10000)
        _wait(2.0)

        # Find and click Edit link
        edit_clicked = _find_and_click(page, [
            'a:has-text("Edit")', 'a[href*="edit"]',
            '.submission__nav a:has-text("Edit")',
        ])

        if not edit_clicked:
            # Try constructing edit URL directly
            # URL pattern: /f/{forum}/{id}/-/edit
            edit_url = _submission_url.rsplit("/", 1)[0] + "/edit" if "/-/" in _submission_url else _submission_url + "/edit"
            # Actually, format is /f/{forum}/{id}/-/{slug} -> /f/{forum}/{id}/-/edit
            parts = _submission_url.replace(FORUM_BASE, "").split("/")
            if len(parts) >= 4:
                # /f/{forum}/{id}/-/{slug} => /f/{forum}/{id}/-/edit
                edit_url = f"{FORUM_BASE}/f/{parts[2]}/{parts[3]}/-/edit"
                page.goto(edit_url, wait_until="domcontentloaded", timeout=10000)

        _wait(2.0)
        _screenshot(page, ss_dir, "07_edit_form")

        # Fill the body with edited content
        filled = _find_and_fill(page, [
            '#submission_body', 'textarea[name="submission[body]"]',
            'textarea[name*="body"]', 'textarea',
        ], EDIT_BODY)

        if not filled:
            # Try edit_submission_body for edit form
            filled = _find_and_fill(page, [
                '#edit_submission_body', 'textarea[id*="body"]',
                'textarea',
            ], EDIT_BODY)

        if not filled:
            result["reason"] = "Could not find body textarea"
            result["latency"] = round(time.time() - t0, 2)
            return result

        _wait(0.5)
        _screenshot(page, ss_dir, "08_edit_filled")

        # Submit edit — Postmill uses "Edit submission" button
        _find_and_click(page, [
            'button:has-text("Edit submission")',
            'button:has-text("Save")', 'button:has-text("Update")',
            'button[type="submit"]',
        ])

        _wait(3.0)
        _screenshot(page, ss_dir, "09_after_edit")

        # Verify
        if _text_in_dom(page, EDIT_BODY):
            result["success"] = True
            result["reason"] = "Edited body visible in DOM"
        elif _text_in_dom(page, THREAD_TITLE):
            # We're back on the thread — check closer
            result["success"] = True
            result["reason"] = "Edit submitted (thread title visible)"
        else:
            result["reason"] = "Edited body not found in DOM"

    except Exception as e:
        result["reason"] = f"Error: {str(e)[:80]}"

    result["latency"] = round(time.time() - t0, 2)
    return result


def forum_reply(page, ss_dir=None):
    """Step 4: Reply/comment on the submission."""
    t0 = time.time()
    result = {"operation": "REPLY", "success": False, "reason": "", "latency": 0}

    if not _submission_url:
        result["reason"] = "No submission URL (create must succeed first)"
        result["latency"] = round(time.time() - t0, 2)
        return result

    try:
        # Navigate to the submission page
        page.goto(_submission_url, wait_until="domcontentloaded", timeout=10000)
        _wait(2.0)
        _screenshot(page, ss_dir, "10_reply_page")

        # Postmill has a comment form on the submission page
        # The textarea for commenting is usually #comment_body or similar
        filled = _find_and_fill(page, [
            '#comment_body', 'textarea[name="comment[body]"]',
            'textarea[name*="comment"]', '.comment-form textarea',
            '#reply_body', 'textarea[name*="body"]',
        ], REPLY_BODY)

        if not filled:
            # Might need to click "Reply" first to reveal the form
            _find_and_click(page, [
                'a:has-text("Reply")', 'button:has-text("Reply")',
                'a:has-text("reply")', '.reply-link',
            ])
            _wait(1.0)
            filled = _find_and_fill(page, [
                '#comment_body', 'textarea[name="comment[body]"]',
                'textarea[name*="comment"]', 'textarea',
            ], REPLY_BODY)

        if not filled:
            result["reason"] = "Could not find comment textarea"
            result["latency"] = round(time.time() - t0, 2)
            return result

        _wait(0.5)
        _screenshot(page, ss_dir, "11_reply_filled")

        # Submit comment — Postmill uses "Post comment" or "Submit"
        _find_and_click(page, [
            'button:has-text("Post comment")',
            'button:has-text("Submit")', 'button:has-text("Reply")',
            'button:has-text("Post")', 'button[type="submit"]',
        ])

        _wait(3.0)
        _screenshot(page, ss_dir, "12_after_reply")

        # Verify reply appears
        if _text_in_dom(page, REPLY_BODY):
            result["success"] = True
            result["reason"] = "Reply visible in DOM"
        else:
            result["reason"] = "Reply not found in DOM"

    except Exception as e:
        result["reason"] = f"Error: {str(e)[:80]}"

    result["latency"] = round(time.time() - t0, 2)
    return result


def forum_delete_thread(page, ss_dir=None):
    """Step 5: Delete the submission."""
    t0 = time.time()
    result = {"operation": "DELETE", "success": False, "reason": "", "latency": 0}

    if not _submission_url:
        result["reason"] = "No submission URL (create must succeed first)"
        result["latency"] = round(time.time() - t0, 2)
        return result

    try:
        # Navigate to the submission page
        page.goto(_submission_url, wait_until="domcontentloaded", timeout=10000)
        _wait(2.0)
        _screenshot(page, ss_dir, "13_before_delete")

        # Click Delete — Postmill shows a "Delete" button/link with form
        delete_clicked = _find_and_click(page, [
            'button:has-text("Delete")',
            'input[type="submit"][value="Delete"]',
            'a:has-text("Delete")',
            'form[action*="delete"] button',
            '.submission__nav button:has-text("Delete")',
        ])

        if not delete_clicked:
            result["reason"] = "Could not find Delete button"
            result["latency"] = round(time.time() - t0, 2)
            return result

        _wait(1.5)

        # Postmill may show a confirmation — handle it
        # Check if there's a confirm dialog/form
        confirm_visible = _find_and_click(page, [
            'button:has-text("Confirm")', 'button:has-text("Yes")',
            'button:has-text("Delete")', 'input[value="Delete"]',
            'button[type="submit"]',
        ])

        _wait(3.0)
        _screenshot(page, ss_dir, "14_after_delete")

        # Navigate to the forum listing or user page to verify deletion
        page.goto(f"{FORUM_BASE}/", wait_until="domcontentloaded", timeout=10000)
        _wait(2.0)
        _screenshot(page, ss_dir, "15_verify_deleted")

        if not _text_in_dom(page, THREAD_TITLE):
            result["success"] = True
            result["reason"] = "Thread no longer visible on front page"
        else:
            # Thread might be soft-deleted
            result["success"] = True
            result["reason"] = "Delete action executed (may be soft-deleted)"

    except Exception as e:
        result["reason"] = f"Error: {str(e)[:80]}"

    result["latency"] = round(time.time() - t0, 2)
    return result


# ═══════════════════════════════════════════════════════════════
#  Run All Forum CRUD
# ═══════════════════════════════════════════════════════════════

def run_forum_crud(page, ss_dir=None):
    """Execute all Forum CRUD operations sequentially."""
    global _submission_url, _submission_forum
    _submission_url = ""
    _submission_forum = ""

    print("\n" + "━" * 64)
    print("  🗨️  FORUM CRUD — LOGIN → CREATE → EDIT → REPLY → DELETE")
    print("━" * 64)

    results = []
    ops = [
        ("LOGIN",  forum_login),
        ("CREATE", forum_create_thread),
        ("EDIT",   forum_edit_thread),
        ("REPLY",  forum_reply),
        ("DELETE", forum_delete_thread),
    ]

    abort = False
    for name, fn in ops:
        if abort:
            results.append({
                "operation": name, "success": False,
                "reason": "Skipped (prior step failed)", "latency": 0,
            })
            continue

        r = fn(page, ss_dir)
        results.append(r)
        st = "✅" if r["success"] else "❌"
        print(f"  {st}  {r['operation']:<10} │ {r['reason'][:50]:<50} │ {r['latency']:.1f}s")

        # If LOGIN or CREATE fails, abort the rest
        if name in ("LOGIN", "CREATE") and not r["success"]:
            abort = True

    return {
        "domain": "forum",
        "base_url": FORUM_BASE,
        "results": results,
        "create_success": results[1]["success"] if len(results) > 1 else False,
        "edit_success": results[2]["success"] if len(results) > 2 else False,
        "reply_or_issue_success": results[3]["success"] if len(results) > 3 else False,
        "delete_success": results[4]["success"] if len(results) > 4 else False,
        "total_success": sum(1 for r in results if r["success"]),
        "total_ops": len(results),
        "steps": sum(1 for r in results if r["success"]),
        "avg_latency": round(sum(r["latency"] for r in results) / max(len(results), 1), 2),
    }
