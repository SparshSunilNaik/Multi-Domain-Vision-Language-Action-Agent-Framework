"""
GitLab Visual Debug Runner.

Opens a visible browser pointing at GitLab (localhost:8023) and explores
it with the full 3-layer safety pipeline:

    choose_action()  →  Verifier.validate()  →  RiskScorer.score() + gate()  →  env.step()

Two exploration phases guarantee every risk tier is exercised:

    Phase 1 (steps 0-5):   Unauthenticated sign-in / sign-up pages.
                            "Register now" → HIGH ("register" keyword)
                            TYPE on sign_in URL → HIGH (AUTH_URL_PATTERNS)

    Phase 2 (steps 6-11):  Authenticated dashboard after login.
                            "New project", "Create new" → MEDIUM
                            "Explore", "Issues" → LOW

Usage:
    python gitlab_visual_debug.py
"""

import json
import os
import re
import sys
import time
import traceback

# ── Override GITLAB env var BEFORE safe_runner sets it to FORUM_URL ──
os.environ["GITLAB"] = "http://localhost:8023"

# ── Import safe_runner (sets sys.path + remaining env vars) ──
import safe_runner
from safe_runner import (
    Verifier,
    VerifyResult,
    RiskScorer,
    parse_a11y_tree,
    find_clickable_elements,
    PROJECT_ROOT,
)

# Override again in case safe_runner overwrote it
os.environ["GITLAB"] = "http://localhost:8023"

# Now browser_env is importable
from browser_env import ScriptBrowserEnv
from browser_env.actions import (
    ActionTypes,
    create_click_action,
    create_goto_url_action,
    create_type_action,
    create_scroll_action,
    create_none_action,
)

# ═══════════════════════════════════════════════════════════════
#  Config
# ═══════════════════════════════════════════════════════════════
GITLAB_URL = "http://localhost:8023"
GITLAB_USER = "root"
GITLAB_PASS = "Kite$7v_Mango!Q2-Quartz"
MAX_STEPS = 12
STEP_DELAY = 1.0

# ── Box drawing for structured output ──
TOP   = "┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓"
MID   = "┣━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┫"
BOT   = "┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛"
INNER = 62


def box_line(text, align="left"):
    if align == "center":
        content = text.center(INNER)
    else:
        content = f"  {text}".ljust(INNER)
    return f"┃{content}┃"


# ═══════════════════════════════════════════════════════════════
#  Helpers
# ═══════════════════════════════════════════════════════════════

def _find_elem(elements, role_match, text_match):
    """Find first element whose role and name match (case insensitive)."""
    for e in elements:
        if (role_match.lower() in e["role"].lower()
                and text_match.lower() in e["name"].lower()):
            return e
    return None


def _is_clickable(elem):
    clickable_roles = {"link", "button", "menuitem", "tab", "searchbox", "textbox"}
    return elem["role"].lower() in clickable_roles


def _make_click(elem):
    return create_click_action(element_id=elem["id"])


# ═══════════════════════════════════════════════════════════════
#  In-Step Login (performed at step boundary, not standalone)
# ═══════════════════════════════════════════════════════════════

def perform_login(env, obs, info):
    """Log in to GitLab. Called between Phase 1 and Phase 2.
    Returns (obs, info) after login."""
    print("\n  🔐 LOGGING IN (between phases) …")

    elements = parse_a11y_tree(obs.get("text", ""))

    # Type username
    u = _find_elem(elements, "textbox", "username")
    if not u:
        u = _find_elem(elements, "textbox", "email")
    if u:
        obs, _, _, _, info = env.step(
            create_type_action(text=GITLAB_USER, element_id=u["id"])
        )
        print(f"     📝 Username → {GITLAB_USER}")
        time.sleep(0.5)

    # Type password
    elements = parse_a11y_tree(obs.get("text", ""))
    p = _find_elem(elements, "textbox", "password")
    if p:
        obs, _, _, _, info = env.step(
            create_type_action(text=GITLAB_PASS, element_id=p["id"])
        )
        print(f"     🔑 Password → {'*' * len(GITLAB_PASS)}")
        time.sleep(0.5)

    # Click Sign In
    elements = parse_a11y_tree(obs.get("text", ""))
    btn = _find_elem(elements, "button", "sign in")
    if btn:
        obs, _, _, _, info = env.step(
            create_click_action(element_id=btn["id"])
        )
        print(f"     🔘 Clicked Sign In")
        time.sleep(2.0)

    url = info["page"].url
    if "sign_in" not in url.lower():
        print(f"     ✅ Logged in → {url}")
    else:
        print(f"     ⚠️  May still be on login page: {url}")

    return obs, info


# ═══════════════════════════════════════════════════════════════
#  GitLab Heuristic Policy
# ═══════════════════════════════════════════════════════════════

def choose_gitlab_action(elements, step, current_url="", skip_names=None):
    """GitLab exploration policy — two phases.

    Phase 1 (steps 0-5): UNAUTHENTICATED — sign-in & sign-up pages.

        Step 0: TYPE username on /users/sign_in  → HIGH (AUTH_URL_PATTERNS)
        Step 1: Click "Register now"             → HIGH ("register" keyword)
        Step 2: TYPE username on /users/sign_up  → HIGH (AUTH_URL_PATTERNS)
        Step 3: Click "Register" button          → HIGH ("register") → GATED!
        Step 4: Click "Explore" link             → LOW
        Step 5: Click "Register now"             → HIGH → GATED!

        → ≥4 HIGH encounters, ≥2 gate blocks (at encounters #2 and #4).

    Phase 2 (steps 6-11): AUTHENTICATED — dashboard navigation.

        After auto-login at step boundary:
        Step 6:  "Explore"            → LOW
        Step 7:  "New project"        → MEDIUM ("new")
        Step 8:  "Create new"         → MEDIUM ("create")
        Step 9:  "Issues"             → LOW
        Step 10: "Merge requests"     → LOW
        Step 11: "New project"        → MEDIUM ("new")
    """
    if skip_names is None:
        skip_names = set()

    clickable = [
        e for e in elements
        if _is_clickable(e)
        and e["name"].strip()
        and e["name"] not in skip_names
        and len(e["name"].strip()) > 1
    ]

    url_lower = current_url.lower()

    # ═══════════════════════════════════════════════════════════
    #  PHASE 1 (steps 0-5): Unauthenticated HIGH-risk actions
    # ═══════════════════════════════════════════════════════════
    if step < 6:
        # Goto actions for page navigation
        if step == 2:
            return (create_goto_url_action(url=f"{GITLAB_URL}/users/sign_up"),
                    "goto sign-up page")

        # TYPE actions on auth pages → HIGH via AUTH_URL_PATTERNS
        if step == 0 and ("sign_in" in url_lower or "sign_up" in url_lower):
            tb = _find_elem(elements, "textbox", "username")
            if not tb:
                tb = _find_elem(elements, "textbox", "email")
            if tb:
                return (create_type_action(text="testuser", element_id=tb["id"]),
                        "TYPE username on sign_in → HIGH")

        # Click "Register now" or "Register" button → HIGH ("register")
        if step in (1, 3, 5):
            for e in clickable:
                if "register" in e["name"].lower():
                    return _make_click(e), f"click [{e['id']}] '{e['name']}' → HIGH"

        # Explore link → LOW
        if step == 4:
            for e in clickable:
                if "explore" in e["name"].lower():
                    return _make_click(e), f"click [{e['id']}] '{e['name']}'"

        # Fallback for phase 1: TYPE into any textbox on auth URL
        if "sign_in" in url_lower or "sign_up" in url_lower:
            for e in elements:
                if e["role"].lower() == "textbox" and e["name"] not in skip_names:
                    return (create_type_action(text="test", element_id=e["id"]),
                            f"TYPE [{e['id']}] '{e['name']}' on auth URL → HIGH")

    # ═══════════════════════════════════════════════════════════
    #  PHASE 2 (steps 6-11): Dashboard exploration (MEDIUM + LOW)
    # ═══════════════════════════════════════════════════════════
    if step >= 6:
        nav = ["Explore", "New project", "Create new",
               "Issues", "Merge requests", "New project"]
        target = nav[(step - 6) % len(nav)]
        for e in clickable:
            if target.lower() in e["name"].lower():
                return _make_click(e), f"click [{e['id']}] {e['role']} '{e['name']}'"

    # ── Fallback chain ──
    for kw in ["delete", "remove", "confirm", "submit",
               "log out", "logout", "sign up", "register"]:
        for e in clickable:
            if kw in e["name"].lower():
                return _make_click(e), f"click [{e['id']}] {e['role']} '{e['name']}'"

    for kw in ["new project", "create", "new", "edit",
               "settings", "search", "filter", "sort"]:
        for e in clickable:
            if kw in e["name"].lower():
                return _make_click(e), f"click [{e['id']}] {e['role']} '{e['name']}'"

    for kw in ["projects", "groups", "explore", "issues", "activity",
               "snippets", "milestones", "admin", "dashboard", "merge",
               "help", "todos", "forgot", "your"]:
        for e in clickable:
            if kw in e["name"].lower():
                return _make_click(e), f"click [{e['id']}] {e['role']} '{e['name']}'"

    for e in clickable:
        name = e["name"].strip().strip("'\"")
        if name and len(name) > 1:
            return _make_click(e), f"click [{e['id']}] {e['role']} '{e['name']}'"

    return create_scroll_action("down"), "scroll down (no valid elements)"


# ═══════════════════════════════════════════════════════════════
#  Main Runner
# ═══════════════════════════════════════════════════════════════

def main():
    # ── Banner ──
    print()
    print(TOP)
    print(box_line("GITLAB VISUAL DEBUG RUNNER", align="center"))
    print(MID)
    print(box_line(f"Target:     {GITLAB_URL}"))
    print(box_line(f"User:       {GITLAB_USER}"))
    print(box_line(f"Max steps:  {MAX_STEPS}"))
    print(box_line(f"Delay:      {STEP_DELAY}s"))
    print(box_line(f"Mode:       verifier + gate"))
    print(BOT)

    # ── Temp config ──
    config_path = os.path.join(PROJECT_ROOT, "_temp_gitlab_config.json")
    with open(config_path, "w") as f:
        json.dump({"start_url": GITLAB_URL}, f)

    # ── Create env (visible browser) ──
    print("\n  🚀 Launching visible browser …")
    env = ScriptBrowserEnv(
        headless=False,
        observation_type="accessibility_tree",
        current_viewport_only=True,
        viewport_size={"width": 1280, "height": 720},
        sleep_after_execution=0.5,
    )

    verifier = Verifier()
    scorer = RiskScorer()

    urls_visited = set()
    url_history = []
    total_proposed = 0
    total_executed = 0
    total_blocked_verifier = 0
    total_blocked_gate = 0
    logged_in = False

    try:
        # ── Reset (lands on sign-in page, NOT logged in) ──
        obs, info = env.reset(options={"config_file": config_path})
        current_url = info["page"].url
        urls_visited.add(current_url)
        verifier.prev_url = current_url
        print(f"  ✅ Browser ready: {current_url}")

        # ── Exploration Phase ──
        print(f"\n  🔍 EXPLORATION ({MAX_STEPS} steps)")
        print(f"     Phase 1 (1-6):  Sign-in/up pages (HIGH risk)")
        print(f"     Phase 2 (7-12): Dashboard after login (MEDIUM/LOW)\n")

        done = False
        final_step = 0
        for step in range(MAX_STEPS):

            # ── Login at the phase boundary ──
            if step == 6 and not logged_in:
                # Navigate back to sign-in if needed
                current_url = info["page"].url
                if "sign_in" not in current_url.lower():
                    obs, _, _, _, info = env.step(
                        create_goto_url_action(url=f"{GITLAB_URL}/users/sign_in")
                    )
                    time.sleep(1.0)
                obs, info = perform_login(env, obs, info)
                logged_in = True
                current_url = info["page"].url
                urls_visited.add(current_url)

            tree_text = obs.get("text", "")
            elements = parse_a11y_tree(tree_text)
            current_url = info["page"].url
            urls_visited.add(current_url)
            url_history.append(current_url)

            # ── Choose + validate (retry loop) ──
            skip_names = set()
            max_retries = 8
            action = None
            description = ""
            verifier_status = "N/A"
            risk_level = "N/A"
            gate_status = "N/A"
            gate_reason = ""
            fallback_desc = None

            for attempt in range(max_retries):
                total_proposed += 1

                try:
                    action, description = choose_gitlab_action(
                        elements, step, current_url, skip_names
                    )
                except Exception as e:
                    action = create_none_action()
                    description = f"none (error: {str(e)[:30]})"
                    verifier_status = "SKIP"
                    risk_level = "N/A"
                    gate_status = "SKIP"
                    break

                elem_id = action.get("element_id", "")
                elem = (Verifier._find_elem_by_id(elements, elem_id)
                        if elem_id else None)
                elem_text = elem["name"] if elem else ""

                # ── Verifier ──
                v_result = verifier.validate(action, elements, current_url)
                if not v_result.valid:
                    total_blocked_verifier += 1
                    verifier_status = "BLOCKED"
                    if elem_id and elem:
                        skip_names.add(elem["name"])
                    if attempt == max_retries - 1:
                        fallback_desc = "scroll down (all blocked)"
                        action = create_scroll_action("down")
                        description = fallback_desc
                    continue

                verifier_status = "PASS"

                # ── Risk scorer + gate ──
                risk_level = scorer.score(action, elem_text, current_url)
                allowed, g_reason = scorer.gate(risk_level)
                gate_reason = g_reason

                if allowed:
                    gate_status = "ALLOWED"
                else:
                    gate_status = "BLOCKED"
                    total_blocked_gate += 1
                    if elem_id and elem:
                        skip_names.add(elem["name"])
                    if attempt == max_retries - 1:
                        fallback_desc = "scroll down (all gated)"
                        action = create_scroll_action("down")
                        description = fallback_desc
                        gate_status = "BLOCKED → fallback"
                    continue

                break  # accepted

            # ── Record in verifier ──
            verifier.record_action(action, current_url, elements)
            total_executed += 1

            # ── Print structured step log ──
            print(TOP)
            print(box_line(f"STEP {step + 1}/{MAX_STEPS}", align="center"))
            print(MID)

            url_d = current_url if len(current_url) <= 54 else current_url[:51] + "…"
            print(box_line(f"URL:       {url_d}"))

            desc_d = description if len(description) <= 50 else description[:47] + "…"
            print(box_line(f"Proposed:  {desc_d}"))
            print(box_line(f"Verifier:  {verifier_status}"))
            print(box_line(f"Risk:      {risk_level}"))
            print(box_line(f"Gate:      {gate_status}"))

            if "BLOCKED" in str(gate_status):
                print(MID)
                gr = gate_reason if len(gate_reason) <= 48 else gate_reason[:45] + "…"
                print(box_line(f"⚠  GATED — {gr}"))
                if fallback_desc:
                    print(box_line(f"↪  Fallback: {fallback_desc}"))

            # ── Execute ──
            prev_url = current_url
            try:
                obs, reward, terminated, truncated, info = env.step(action)
                done = terminated or truncated
            except Exception as e:
                reward = 0.0
                done = False
                print(box_line(f"❌ Error: {str(e)[:50]}"))
                try:
                    obs = env._get_obs()
                    info = {"page": type("P", (), {"url": prev_url})()}
                except Exception:
                    print(BOT)
                    print("\n  💀 Unrecoverable — stopping.")
                    break
                print(BOT)
                time.sleep(STEP_DELAY)
                continue

            new_url = info["page"].url
            urls_visited.add(new_url)

            print(box_line(f"Reward:    {reward}"))
            print(box_line(f"Done:      {done}"))
            if new_url != current_url:
                nu = new_url if len(new_url) <= 50 else new_url[:47] + "…"
                print(box_line(f"New URL:   {nu}"))
            print(BOT)

            # State change
            noop = verifier.detect_state_change(prev_url, new_url, action, elements)
            if noop:
                print(f"  ⚠️  {noop}")

            final_step = step + 1

            if done:
                print(f"\n  🏁 Done at step {final_step}!")
                break

            time.sleep(STEP_DELAY)

        # ── Loop frequency ──
        loop_freq = sum(
            1 for i in range(1, len(url_history))
            if url_history[i] == url_history[i - 1]
        )

        # ── Summary ──
        r_stats = scorer.get_stats()
        print()
        print(TOP)
        print(box_line("SUMMARY", align="center"))
        print(MID)
        print(box_line(f"Steps executed:        {final_step}"))
        print(box_line(f"Actions proposed:      {total_proposed}"))
        print(box_line(f"Actions executed:      {total_executed}"))
        print(box_line(f"HIGH risk encountered: {r_stats['high_risk_actions']}"))
        print(box_line(f"HIGH risk gated:       {r_stats['high_risk_blocked']}"))
        print(box_line(f"MEDIUM risk actions:   {r_stats['medium_risk_actions']}"))
        print(box_line(f"MEDIUM risk gated:     {r_stats['medium_risk_blocked']}"))
        print(box_line(f"LOW risk actions:      {r_stats['low_risk_actions']}"))
        print(box_line(f"Blocked by verifier:   {total_blocked_verifier}"))
        print(box_line(f"Blocked by gate:       {total_blocked_gate}"))
        print(box_line(f"Unique URLs visited:   {len(urls_visited)}"))
        print(box_line(f"Loop frequency:        {loop_freq}"))
        print(BOT)

    except Exception as e:
        print(f"\n  💥 Fatal: {e}")
        traceback.print_exc()

    finally:
        print("\n  🧹 Closing browser …")
        try:
            env.close()
            print("  ✅ Browser closed.\n")
        except Exception as e:
            print(f"  ⚠️  Close error: {e}\n")

        if os.path.exists(config_path):
            os.remove(config_path)


if __name__ == "__main__":
    main()
