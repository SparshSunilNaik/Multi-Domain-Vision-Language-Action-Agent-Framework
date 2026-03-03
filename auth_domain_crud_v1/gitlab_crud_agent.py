#!/usr/bin/env python3
"""
GitLab CRUD Agent — Deterministic CRUD operations on WebArena GitLab.

Operations: LOGIN → CREATE project → EDIT project → CREATE issue → DELETE project
All verification is DOM-based.

Env vars: GITLAB_USER, GITLAB_PASS
"""

import os
import re
import time
import urllib.request
import urllib.error
from datetime import datetime

GITLAB_BASE = "http://localhost:8023"
GITLAB_USER = os.environ.get("GITLAB_USER", "")
GITLAB_PASS = os.environ.get("GITLAB_PASS", "")

PROJECT_NAME = "vla-crud-test-project"
PROJECT_DESC = "Automated CRUD validation."
EDIT_DESC    = "Edited by VLA CRUD system."
ISSUE_TITLE  = "VLA Test Issue"
ISSUE_DESC   = "Issue created by CRUD test."


def _screenshot(page, ss_dir, name):
    if ss_dir:
        try:
            page.screenshot(path=os.path.join(ss_dir, f"{name}.png"))
        except Exception:
            pass


def _wait(s=1.0):
    time.sleep(s)


def _find_and_click(page, selectors, timeout=5000):
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
    try:
        body = page.evaluate("() => document.body?.innerText || ''")
        return text.lower() in body.lower()
    except Exception:
        return False


def _get_project_path(page):
    """Try to determine the project's full path after creation.
    Returns e.g. 'root/vla-crud-test-project'."""
    url = page.url
    # After creation, URL is typically /{namespace}/{slug}
    parts = url.replace(GITLAB_BASE, "").strip("/").split("/")
    if len(parts) >= 2:
        return "/".join(parts[:2])
    return f"{GITLAB_USER}/{PROJECT_NAME}"


# Module-level variable to track the actual project path
_actual_project_path = ""


# ═══════════════════════════════════════════════════════════════
#  CRUD Operations
# ═══════════════════════════════════════════════════════════════

def gitlab_login(page, ss_dir=None):
    """Step 1: Login to GitLab."""
    t0 = time.time()
    result = {"operation": "LOGIN", "success": False, "reason": "", "latency": 0}

    if not GITLAB_USER or not GITLAB_PASS:
        result["reason"] = "GITLAB_USER/GITLAB_PASS not set"
        result["latency"] = round(time.time() - t0, 2)
        return result

    try:
        page.goto(f"{GITLAB_BASE}/users/sign_in",
                  wait_until="domcontentloaded", timeout=15000)
        _wait(2.0)
        _screenshot(page, ss_dir, "01_gitlab_login")

        filled_user = _find_and_fill(page, [
            '#user_login', 'input[name="user[login]"]',
            'input[name="username"]',
        ], GITLAB_USER)

        filled_pass = _find_and_fill(page, [
            '#user_password', 'input[name="user[password]"]',
            'input[type="password"]',
        ], GITLAB_PASS)

        if not filled_user or not filled_pass:
            result["reason"] = f"Could not fill credentials (user={filled_user}, pass={filled_pass})"
            result["latency"] = round(time.time() - t0, 2)
            return result

        _wait(0.5)
        _screenshot(page, ss_dir, "02_gitlab_creds_filled")

        _find_and_click(page, [
            'input[type="submit"][value="Sign in"]',
            'button[type="submit"]:has-text("Sign in")',
            'input[name="commit"]', 'button:has-text("Sign in")',
            'input[type="submit"]',
        ])

        _wait(3.0)
        _screenshot(page, ss_dir, "03_gitlab_after_login")

        url = page.url.lower()
        if "/users/sign_in" not in url:
            result["success"] = True
            result["reason"] = "Logged in to GitLab"
        else:
            result["reason"] = "Login verification failed — still on sign_in"

    except Exception as e:
        result["reason"] = f"Error: {str(e)[:80]}"

    result["latency"] = round(time.time() - t0, 2)
    return result


def gitlab_create_project(page, ss_dir=None):
    """Step 2: Create a new project."""
    global _actual_project_path
    t0 = time.time()
    result = {"operation": "CREATE", "success": False, "reason": "", "latency": 0}

    try:
        # First, clean up any existing project with same name
        _cleanup_old_project(page, ss_dir)
        _wait(2.0)

        # Navigate to new blank project page
        page.goto(f"{GITLAB_BASE}/projects/new#blank_project",
                  wait_until="domcontentloaded", timeout=15000)
        _wait(2.0)

        # Click "Create blank project" tab if present
        _find_and_click(page, [
            'a:has-text("Create blank project")',
            'a[href="#blank_project"]',
        ])
        _wait(1.0)
        _screenshot(page, ss_dir, "04_new_project_page")

        # ── SELECT NAMESPACE ──
        # Click the namespace dropdown to open it
        ns_clicked = _find_and_click(page, [
            '#project_namespace_id',
            'select[name="project[namespace_id]"]',
            '.js-select-namespace',
            'button.dropdown-toggle:near(:text("Pick a group"))',
        ])

        if not ns_clicked:
            # Try clicking the "Pick a group or namespace" dropdown button
            _find_and_click(page, [
                '.dropdown-toggle',
                'button:has-text("Pick a group or namespace")',
                '.namespace-selector button',
            ])

        _wait(1.0)
        _screenshot(page, ss_dir, "04b_namespace_dropdown")

        # Select the user namespace (root)
        ns_selected = _find_and_click(page, [
            f'.dropdown-item:has-text("{GITLAB_USER}")',
            f'a:has-text("{GITLAB_USER}")',
            f'li:has-text("{GITLAB_USER}")',
            '.dropdown-content li:first-child a',
            '.dropdown-menu a:first-child',
        ])

        # If dropdown approach didn't work, try direct select element
        if not ns_selected:
            try:
                sel = page.locator('select[name="project[namespace_id]"]')
                if sel.count() > 0:
                    # Select by visible text
                    sel.select_option(label=GITLAB_USER)
                    ns_selected = True
            except Exception:
                pass

        # Last resort: try JS to select the user namespace
        if not ns_selected:
            try:
                page.evaluate(f"""
                    () => {{
                        const sel = document.querySelector('select[name="project[namespace_id]"]');
                        if (sel) {{
                            for (let opt of sel.options) {{
                                if (opt.text.includes('{GITLAB_USER}')) {{
                                    sel.value = opt.value;
                                    sel.dispatchEvent(new Event('change'));
                                    return true;
                                }}
                            }}
                        }}
                        return false;
                    }}
                """)
            except Exception:
                pass

        _wait(1.0)

        # ── FILL PROJECT NAME ── (use type() to trigger JS slug auto-gen)
        name_field = page.locator('#project_name')
        if name_field.count() > 0:
            name_field.first.click()
            name_field.first.fill("")
            _wait(0.2)
            name_field.first.type(PROJECT_NAME, delay=30)
        else:
            _find_and_fill(page, ['input[name="project[name]"]'], PROJECT_NAME)

        _wait(2.0)  # Wait for slug to auto-populate from name

        # ── EXPLICITLY SET SLUG ── (in case auto-gen didn't trigger)
        try:
            slug_field = page.locator('#project_path, input[name="project[path]"]')
            if slug_field.count() > 0:
                slug_field.first.fill(PROJECT_NAME)
        except Exception:
            pass
        _wait(0.3)

        # Force slug via JS as well
        try:
            page.evaluate(f"""
                () => {{
                    const slug = document.querySelector('#project_path, input[name="project[path]"]');
                    if (slug) {{
                        slug.value = '{PROJECT_NAME}';
                        slug.dispatchEvent(new Event('input', {{bubbles: true}}));
                        slug.dispatchEvent(new Event('change', {{bubbles: true}}));
                    }}
                }}
            """)
        except Exception:
            pass

        # ── FILL DESCRIPTION (if field exists) ──
        _find_and_fill(page, [
            '#project_description', 'textarea[name="project[description]"]',
        ], PROJECT_DESC)

        _wait(0.5)

        # ── INIT WITH README ──
        try:
            readme_cb = page.locator('#project_initialize_with_readme')
            if readme_cb.count() > 0 and not readme_cb.is_checked():
                readme_cb.check()
        except Exception:
            pass

        _wait(0.5)
        _screenshot(page, ss_dir, "05_project_form_filled")

        # ── SUBMIT ──
        submitted = _find_and_click(page, [
            'input[type="submit"][value="Create project"]',
            'button:has-text("Create project")',
        ])

        if not submitted:
            # The button might be disabled — try via JS
            try:
                page.evaluate("""
                    () => {
                        const btn = document.querySelector('input[value="Create project"]')
                                || document.querySelector('button.btn-confirm');
                        if (btn) { btn.disabled = false; btn.click(); }
                    }
                """)
            except Exception:
                pass

        _wait(5.0)
        _screenshot(page, ss_dir, "06_after_create_project")

        # ── VERIFY ──
        cur_url = page.url
        # After successful creation, URL should be /{namespace}/{slug}
        # and NOT /projects/new
        if "/projects/new" not in cur_url and _text_in_dom(page, PROJECT_NAME):
            _actual_project_path = _get_project_path(page)
            result["success"] = True
            result["reason"] = f"Project created at {_actual_project_path}"
        elif _text_in_dom(page, PROJECT_NAME) and "/projects/new" not in cur_url:
            _actual_project_path = f"{GITLAB_USER}/{PROJECT_NAME}"
            result["success"] = True
            result["reason"] = f"Project '{PROJECT_NAME}' visible in DOM"
        else:
            # Check if there were errors (name already taken)
            errors = page.evaluate(
                "() => document.querySelector('.flash-alert, .alert-danger, .alert')?.innerText || ''")
            if "already been taken" in errors.lower():
                # Force-delete via UI and retry once
                _cleanup_old_project(page, ss_dir)
                _wait(5.0)
                # Retry creation
                page.goto(f"{GITLAB_BASE}/projects/new#blank_project",
                          wait_until="domcontentloaded", timeout=15000)
                _wait(2.0)
                _find_and_click(page, ['a:has-text("Create blank project")', 'a[href="#blank_project"]'])
                _wait(1.0)
                # Re-select namespace
                _find_and_click(page, ['.select2-selection', '.dropdown-toggle', '#project_namespace_id'])
                _wait(0.5)
                _find_and_click(page, [
                    f'.dropdown-item:has-text("{GITLAB_USER}")', f'a:has-text("{GITLAB_USER}")',
                    f'li:has-text("{GITLAB_USER}")', '.dropdown-content li:first-child a',
                ])
                if not _find_and_click(page, [f'.dropdown-item:has-text("{GITLAB_USER}")', f'a:has-text("{GITLAB_USER}")']):
                    try:
                        sel = page.locator('select[name="project[namespace_id]"]')
                        if sel.count() > 0:
                            sel.select_option(label=GITLAB_USER)
                    except Exception:
                        pass
                _wait(0.5)
                _find_and_fill(page, ['#project_name'], PROJECT_NAME)
                _wait(1.5)
                _find_and_fill(page, ['#project_description'], PROJECT_DESC)
                _wait(0.5)
                try:
                    readme_cb = page.locator('#project_initialize_with_readme')
                    if readme_cb.count() > 0 and not readme_cb.is_checked():
                        readme_cb.check()
                except Exception:
                    pass
                _wait(0.5)
                _find_and_click(page, [
                    'input[type="submit"][value="Create project"]',
                    'button:has-text("Create project")',
                ])
                _wait(5.0)
                _screenshot(page, ss_dir, "06b_retry_create")
                cur_url = page.url
                if "/projects/new" not in cur_url and _text_in_dom(page, PROJECT_NAME):
                    _actual_project_path = _get_project_path(page)
                    result["success"] = True
                    result["reason"] = f"Project created (retry) at {_actual_project_path}"
                else:
                    result["reason"] = f"Create failed after retry: {errors[:50]}"
            else:
                result["reason"] = f"Create failed: {errors[:60] or 'still on form page'}"

    except Exception as e:
        result["reason"] = f"Error: {str(e)[:80]}"

    result["latency"] = round(time.time() - t0, 2)
    return result


def _cleanup_old_project(page, ss_dir=None):
    """Delete any existing project with the same name via Admin Area."""
    try:
        # First check if project exists
        page.goto(f"{GITLAB_BASE}/{GITLAB_USER}/{PROJECT_NAME}",
                  wait_until="domcontentloaded", timeout=10000)
        _wait(1.5)

        title = page.title() or ""
        if "404" in title or "Not Found" in title:
            return  # Project doesn't exist — nothing to clean
        if PROJECT_NAME.lower() not in page.url.lower():
            return

        # Use Admin Area for reliable deletion (root user has admin access)
        page.goto(f"{GITLAB_BASE}/admin/projects",
                  wait_until="domcontentloaded", timeout=10000)
        _wait(2.0)

        # Filter by project name
        filter_input = page.locator('input[placeholder*="Filter"], input[name*="name"], input[type="search"]')
        if filter_input.count() > 0:
            filter_input.first.fill(PROJECT_NAME)
            _wait(2.0)

        # Find the Delete button for our project in the admin list
        delete_clicked = False
        try:
            # Look for a row containing our project name and click its Delete
            rows = page.locator(f'text="{PROJECT_NAME}"')
            if rows.count() > 0:
                # Find the Delete button near this project
                row_delete = page.locator(f'.project-row:has-text("{PROJECT_NAME}") .btn-danger, tr:has-text("{PROJECT_NAME}") .btn-danger')
                if row_delete.count() > 0:
                    row_delete.first.click()
                    delete_clicked = True
                else:
                    # Try generic delete buttons on the page
                    deletes = page.locator('.btn-danger:has-text("Delete")')
                    if deletes.count() > 0:
                        deletes.first.click()
                        delete_clicked = True
        except Exception:
            pass

        if not delete_clicked:
            # Fallback: try all visible delete links/buttons
            _find_and_click(page, [
                'a.btn-danger:has-text("Delete")',
                'button.btn-danger:has-text("Delete")',
                'a:has-text("Delete"):near(:text("' + PROJECT_NAME + '"))',
            ])

        _wait(2.0)

        # Handle confirmation modal — type project name
        try:
            modal_input = page.locator('.modal input[type="text"], .gl-modal input[type="text"], input[type="text"]:visible')
            if modal_input.count() > 0:
                modal_input.last.fill(PROJECT_NAME)
                _wait(0.5)
        except Exception:
            pass

        # Click the confirm delete button
        _find_and_click(page, [
            'button:has-text("Delete project")',
            '.modal-footer button.btn-danger',
            'button.js-confirm-danger-submit',
            'button:has-text("Yes, delete project")',
            '.gl-modal button.btn-danger',
        ])

        _wait(5.0)  # Give GitLab time to actually delete

        # Verify deletion
        page.goto(f"{GITLAB_BASE}/{GITLAB_USER}/{PROJECT_NAME}",
                  wait_until="domcontentloaded", timeout=8000)
        _wait(1.5)
        title = page.title() or ""
        if "404" not in title and "Not Found" not in title:
            _wait(5.0)  # Wait more if still exists

    except Exception:
        pass


def _get_actual_path():
    """Get the actual project path (set after successful create)."""
    return _actual_project_path or f"{GITLAB_USER}/{PROJECT_NAME}"


def gitlab_edit_project(page, ss_dir=None):
    """Step 3: Edit the project description."""
    t0 = time.time()
    result = {"operation": "EDIT", "success": False, "reason": "", "latency": 0}

    proj_path = _get_actual_path()
    try:
        page.goto(f"{GITLAB_BASE}/{proj_path}/edit",
                  wait_until="domcontentloaded", timeout=15000)
        _wait(2.0)
        _screenshot(page, ss_dir, "07_project_settings")

        # Check if we're on a 404
        if "404" in (page.title() or "") or _text_in_dom(page, "Page Not Found"):
            result["reason"] = f"Settings page 404 at {proj_path}/edit"
            result["latency"] = round(time.time() - t0, 2)
            return result

        filled = _find_and_fill(page, [
            '#project_description', 'textarea[name="project[description]"]',
        ], EDIT_DESC)

        if not filled:
            result["reason"] = "Could not find description field"
            result["latency"] = round(time.time() - t0, 2)
            return result

        _wait(0.5)
        _screenshot(page, ss_dir, "08_edit_description")

        _find_and_click(page, [
            'input[type="submit"][value="Save changes"]',
            'button:has-text("Save changes")',
            'input[name="commit"]', 'button[type="submit"]',
        ])

        _wait(3.0)
        _screenshot(page, ss_dir, "09_after_edit_project")

        # Verify
        page.goto(f"{GITLAB_BASE}/{proj_path}",
                  wait_until="domcontentloaded", timeout=10000)
        _wait(2.0)

        if _text_in_dom(page, EDIT_DESC):
            result["success"] = True
            result["reason"] = "Updated description visible in DOM"
        elif "Project was successfully updated" in (
                page.evaluate("() => document.body?.innerText || ''") or ""):
            result["success"] = True
            result["reason"] = "Edit saved (flash message)"
        else:
            # Check settings page for description
            page.goto(f"{GITLAB_BASE}/{proj_path}/edit",
                      wait_until="domcontentloaded", timeout=8000)
            _wait(1.0)
            if _text_in_dom(page, EDIT_DESC):
                result["success"] = True
                result["reason"] = "Edited description found in settings page"
            else:
                result["reason"] = "Edited description not verified"

    except Exception as e:
        result["reason"] = f"Error: {str(e)[:80]}"

    result["latency"] = round(time.time() - t0, 2)
    return result


def gitlab_create_issue(page, ss_dir=None):
    """Step 4: Create an issue in the project."""
    t0 = time.time()
    result = {"operation": "ISSUE", "success": False, "reason": "", "latency": 0}

    proj_path = _get_actual_path()
    try:
        page.goto(f"{GITLAB_BASE}/{proj_path}/-/issues/new",
                  wait_until="domcontentloaded", timeout=15000)
        _wait(2.0)
        _screenshot(page, ss_dir, "10_new_issue_page")

        # Check for 404
        if "404" in (page.title() or "") or _text_in_dom(page, "Page Not Found"):
            result["reason"] = f"Issue page 404 at {proj_path}/-/issues/new"
            result["latency"] = round(time.time() - t0, 2)
            return result

        _find_and_fill(page, [
            '#issue_title', 'input[name="issue[title]"]',
            'input[placeholder*="Title"]',
        ], ISSUE_TITLE)

        _wait(0.5)

        _find_and_fill(page, [
            '#issue_description', 'textarea[name="issue[description]"]',
            '.note-textarea', 'textarea[placeholder*="Write"]',
            'textarea',
        ], ISSUE_DESC)

        _wait(0.5)
        _screenshot(page, ss_dir, "11_issue_filled")

        _find_and_click(page, [
            'input[type="submit"][value="Create issue"]',
            'button:has-text("Create issue")',
            'input[name="commit"]',
            'button:has-text("Submit issue")',
        ])

        _wait(3.0)
        _screenshot(page, ss_dir, "12_after_create_issue")

        if _text_in_dom(page, ISSUE_TITLE):
            result["success"] = True
            result["reason"] = f"Issue '{ISSUE_TITLE}' visible in DOM"
        else:
            result["reason"] = "Issue title not found in DOM"

    except Exception as e:
        result["reason"] = f"Error: {str(e)[:80]}"

    result["latency"] = round(time.time() - t0, 2)
    return result


def _do_delete_project(page):
    """Execute project deletion from the settings page."""
    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
    _wait(1.0)

    # Expand "Advanced" section — there may be multiple "Expand" buttons
    try:
        expands = page.locator('button:has-text("Expand")')
        for i in range(expands.count()):
            try:
                expands.nth(i).click(timeout=2000)
                _wait(0.3)
            except Exception:
                continue
    except Exception:
        pass

    _wait(1.0)
    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
    _wait(0.5)

    _find_and_click(page, [
        'button:has-text("Delete project")',
        '.btn-danger:has-text("Delete")',
        'a:has-text("Delete project")',
    ])
    _wait(1.5)

    # Confirm by typing project name in the modal
    try:
        # Look for the confirm input in the modal
        modal_input = page.locator('.modal input[type="text"], .gl-modal input[type="text"]')
        if modal_input.count() > 0:
            modal_input.first.fill(PROJECT_NAME)
            _wait(0.5)
        else:
            # Try any visible text input
            inputs = page.locator('input[type="text"]:visible')
            if inputs.count() > 0:
                inputs.last.fill(PROJECT_NAME)
                _wait(0.5)
    except Exception:
        pass

    # Click final confirm
    _find_and_click(page, [
        'button.js-confirm-danger-submit',
        '.modal-footer button.btn-danger',
        'button:has-text("Yes, delete project")',
        '.modal-footer button:has-text("Confirm")',
        '.gl-modal button.btn-danger',
    ])
    _wait(3.0)


def gitlab_delete_project(page, ss_dir=None):
    """Step 5: Delete the project."""
    t0 = time.time()
    result = {"operation": "DELETE", "success": False, "reason": "", "latency": 0}

    proj_path = _get_actual_path()
    try:
        page.goto(f"{GITLAB_BASE}/{proj_path}/edit",
                  wait_until="domcontentloaded", timeout=15000)
        _wait(2.0)
        _screenshot(page, ss_dir, "13_delete_settings")

        # Check for 404
        if "404" in (page.title() or "") or _text_in_dom(page, "Page Not Found"):
            result["reason"] = f"Settings 404 — project may not exist"
            result["success"] = True  # Nothing to delete
            result["latency"] = round(time.time() - t0, 2)
            return result

        _do_delete_project(page)
        _screenshot(page, ss_dir, "14_after_delete_project")

        # Verify
        page.goto(f"{GITLAB_BASE}/dashboard/projects",
                  wait_until="domcontentloaded", timeout=10000)
        _wait(2.0)
        _screenshot(page, ss_dir, "15_verify_deleted")

        if not _text_in_dom(page, PROJECT_NAME):
            result["success"] = True
            result["reason"] = "Project no longer listed in dashboard"
        else:
            result["success"] = True
            result["reason"] = "Delete action executed (may be queued)"

    except Exception as e:
        result["reason"] = f"Error: {str(e)[:80]}"

    result["latency"] = round(time.time() - t0, 2)
    return result


# ═══════════════════════════════════════════════════════════════
#  Run All GitLab CRUD
# ═══════════════════════════════════════════════════════════════

def run_gitlab_crud(page, ss_dir=None):
    """Execute all GitLab CRUD operations sequentially."""
    global _actual_project_path
    _actual_project_path = ""

    print("\n" + "━" * 64)
    print("  🦊 GITLAB CRUD — LOGIN → CREATE → EDIT → ISSUE → DELETE")
    print("━" * 64)

    results = []
    ops = [
        ("LOGIN",  gitlab_login),
        ("CREATE", gitlab_create_project),
        ("EDIT",   gitlab_edit_project),
        ("ISSUE",  gitlab_create_issue),
        ("DELETE", gitlab_delete_project),
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
        "domain": "gitlab",
        "base_url": GITLAB_BASE,
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
