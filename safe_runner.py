"""
Deterministic baseline agent runner for Forum-only WebArena tasks.
No LLM. Heuristic policy + Verifier + RiskScorer with Tiered Autonomy Gate.
"""

import json
import os
import re
import sys
import time
import traceback
from collections import deque
from dataclasses import dataclass, field

# ── Environment variables required by browser_env.env_config ──
FORUM_URL = "http://localhost:9999"
os.environ["REDDIT"] = FORUM_URL
os.environ["SHOPPING"] = FORUM_URL
os.environ["SHOPPING_ADMIN"] = FORUM_URL
os.environ["GITLAB"] = FORUM_URL
os.environ["WIKIPEDIA"] = FORUM_URL
os.environ["MAP"] = FORUM_URL
os.environ["HOMEPAGE"] = FORUM_URL

# ── Imports (after env vars are set) ──
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "third_party", "webarena"))

from browser_env import ScriptBrowserEnv
from browser_env.actions import (
    ActionTypes,
    create_click_action,
    create_goto_url_action,
    create_none_action,
    create_scroll_action,
    create_type_action,
    create_stop_action,
)

# ── Constants ──
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
WEBARENA_ROOT = os.path.join(PROJECT_ROOT, "third_party", "webarena")
CONFIG_FILE = os.path.join(WEBARENA_ROOT, "config_files", "test.raw.json")
MAX_STEPS = 15


# ═══════════════════════════════════════════════════════════════
#  Verifier — deterministic pre-step validation layer
# ═══════════════════════════════════════════════════════════════

@dataclass
class VerifyResult:
    """Result of action verification."""
    valid: bool
    reason: str


class Verifier:
    """Deterministic verifier layer that validates actions before execution.

    Checks:
    A) Element Validation — element_id exists, role supports action type
    B) Repetition Detection — blocks if same (URL, element_name) > 2 in last 10
    C) State Change Detection — detects no-ops post-execution
    D) Action Confidence Flag — returns {valid, reason}
    """

    CLICKABLE_ROLES = {
        "link", "button", "menuitem", "tab", "checkbox", "radio",
        "switch", "option", "menuitemcheckbox", "menuitemradio",
        "treeitem", "combobox", "searchbox", "textbox",
    }

    TYPEABLE_ROLES = {
        "textbox", "searchbox", "combobox", "spinbutton", "textarea",
    }

    NON_CLICKABLE_ROLES = {
        "RootWebArea", "main", "complementary", "contentinfo",
        "navigation", "banner", "sectionheader", "heading",
        "StaticText", "InlineTextBox", "generic", "paragraph",
        "list", "listitem", "img", "image", "group", "separator",
        "region", "status", "alert", "log", "marquee", "timer",
        "tooltip", "document", "application", "article", "figure",
        "math", "note", "presentation", "none",
    }

    MAX_REPEAT = 2
    HISTORY_SIZE = 10

    def __init__(self):
        self.history: deque = deque(maxlen=self.HISTORY_SIZE)
        self.prev_url: str = ""
        self.prev_element_name: str = ""
        self.consecutive_same_click: int = 0
        self.total_proposed: int = 0
        self.total_blocked: int = 0
        self.total_noops: int = 0

    def validate(self, action, elements, current_url):
        """Validate an action BEFORE env.step()."""
        self.total_proposed += 1
        action_type = action["action_type"]
        element_id = action.get("element_id", "")

        # (A) Element Validation
        if action_type in (ActionTypes.CLICK, ActionTypes.TYPE, ActionTypes.HOVER):
            if element_id:
                elem = self._find_elem_by_id(elements, element_id)
                if elem is None:
                    self.total_blocked += 1
                    return VerifyResult(
                        valid=False,
                        reason=f"Element [{element_id}] not found in current a11y tree"
                    )

                role_lower = elem["role"].lower()

                if action_type == ActionTypes.CLICK:
                    if role_lower in {r.lower() for r in self.NON_CLICKABLE_ROLES}:
                        self.total_blocked += 1
                        return VerifyResult(
                            valid=False,
                            reason=f"CLICK blocked on non-clickable role '{elem['role']}' "
                                   f"[{element_id}] '{elem['name']}'"
                        )

                elif action_type == ActionTypes.TYPE:
                    if role_lower not in {r.lower() for r in self.TYPEABLE_ROLES}:
                        self.total_blocked += 1
                        return VerifyResult(
                            valid=False,
                            reason=f"TYPE blocked on non-typeable role '{elem['role']}' "
                                   f"[{element_id}] '{elem['name']}'"
                        )

        # (B) Repetition Detection — by (URL, element_name)
        if element_id:
            elem = self._find_elem_by_id(elements, element_id)
            elem_name = elem["name"] if elem else element_id
            pair = (current_url, elem_name)
            repeat_count = sum(1 for h in self.history if h == pair)
            if repeat_count >= self.MAX_REPEAT:
                self.total_blocked += 1
                return VerifyResult(
                    valid=False,
                    reason=f"Repetition limit: ({current_url}, '{elem_name}') "
                           f"appeared {repeat_count} times in last {self.HISTORY_SIZE} actions"
                )

        return VerifyResult(valid=True, reason="All checks passed")

    def record_action(self, action, current_url, elements):
        """Record an action after validation, before execution."""
        element_id = action.get("element_id", "")
        if element_id:
            elem = self._find_elem_by_id(elements, element_id)
            elem_name = elem["name"] if elem else element_id
            self.history.append((current_url, elem_name))

    def detect_state_change(self, prev_url, new_url, action, elements):
        """(C) State Change Detection — call AFTER env.step()."""
        element_id = action.get("element_id", "")
        elem = self._find_elem_by_id(elements, element_id) if element_id else None
        elem_name = elem["name"] if elem else element_id

        if prev_url == new_url and elem_name:
            if elem_name == self.prev_element_name:
                self.consecutive_same_click += 1
                if self.consecutive_same_click >= 2:
                    self.total_noops += 1
                    result = (
                        f"NO-OP detected: URL unchanged ({new_url}), "
                        f"element '{elem_name}' clicked {self.consecutive_same_click} "
                        f"times consecutively"
                    )
                    self.prev_element_name = elem_name
                    self.prev_url = new_url
                    return result
            else:
                self.consecutive_same_click = 0
        else:
            self.consecutive_same_click = 0

        self.prev_element_name = elem_name
        self.prev_url = new_url
        return None

    def get_stats(self):
        return {
            "total_proposed": self.total_proposed,
            "total_blocked": self.total_blocked,
            "total_noops": self.total_noops,
            "history_len": len(self.history),
        }

    @staticmethod
    def _find_elem_by_id(elements, element_id):
        for elem in elements:
            if elem["id"] == element_id:
                return elem
        return None


# ═══════════════════════════════════════════════════════════════
#  RiskScorer — risk-level classification for actions
# ═══════════════════════════════════════════════════════════════

class RiskScorer:
    """Deterministic risk scorer that classifies actions as LOW/MEDIUM/HIGH.

    Rules:
        HIGH:  element text contains destructive/auth keywords
               (submit, delete, remove, confirm, log out, sign up, register)
               OR action is TYPE into a login/registration form field
        MEDIUM: element text contains mutating keywords
               (search, edit, create, new)
               OR action is TYPE into a generic input
        LOW:   navigation links (forums, wiki, home, comments)
               and purely browsing actions (scroll)
    """

    # Keywords that indicate HIGH risk — destructive or auth-mutating
    HIGH_KEYWORDS = {
        "submit", "delete", "remove", "confirm",
        "log out", "logout", "sign up", "register",
    }

    # Keywords that indicate MEDIUM risk — mutating but non-destructive
    MEDIUM_KEYWORDS = {
        "search", "edit", "create", "new", "filter", "sort",
    }

    # Keywords that indicate LOW risk — pure navigation/browsing
    LOW_KEYWORDS = {
        "forums", "wiki", "home", "comments", "submissions",
        "all pages", "recent changes", "alphabetical", "tags",
    }

    # URL patterns for login/registration pages
    AUTH_URL_PATTERNS = {"login", "registration", "register", "signup", "sign-up"}

    def __init__(self):
        # Counters for deterministic gating decisions
        self.high_encounter_count: int = 0
        self.medium_encounter_count: int = 0
        # Stats
        self.total_scored: int = 0
        self.high_risk_actions: int = 0
        self.high_risk_blocked: int = 0
        self.medium_risk_actions: int = 0
        self.medium_risk_blocked: int = 0
        self.low_risk_actions: int = 0

    def score(self, action, element_text, current_url):
        """Score an action's risk level.

        Args:
            action: WebArena action dict
            element_text: the name/text of the target element
            current_url: current page URL

        Returns:
            risk_level: "LOW", "MEDIUM", or "HIGH"
        """
        self.total_scored += 1
        action_type = action["action_type"]
        text_lower = element_text.lower()
        url_lower = current_url.lower()

        # ── HIGH risk checks ──

        # Check if element text contains HIGH-risk keywords
        for keyword in self.HIGH_KEYWORDS:
            if keyword in text_lower:
                self.high_risk_actions += 1
                return "HIGH"

        # TYPE action into a form on login/registration page = HIGH
        if action_type == ActionTypes.TYPE:
            for pattern in self.AUTH_URL_PATTERNS:
                if pattern in url_lower:
                    self.high_risk_actions += 1
                    return "HIGH"

        # ── MEDIUM risk checks ──

        # Check if element text contains MEDIUM-risk keywords
        for keyword in self.MEDIUM_KEYWORDS:
            if keyword in text_lower:
                self.medium_risk_actions += 1
                return "MEDIUM"

        # TYPE action on any generic input (not on auth page) = MEDIUM
        if action_type == ActionTypes.TYPE:
            self.medium_risk_actions += 1
            return "MEDIUM"

        # ── LOW risk (default) ──

        # Navigation links, browsing, scrolling = LOW
        self.low_risk_actions += 1
        return "LOW"

    def gate(self, risk_level):
        """Tiered autonomy gate: decide whether to allow the action.

        Uses deterministic counters to simulate approval rates:
            HIGH:   allow 50% — allow on even encounters (1st, 3rd, 5th...)
                    block on odd encounters (2nd, 4th, 6th...)
            MEDIUM: allow 80% — block every 5th encounter
            LOW:    always allow

        Returns:
            (allowed: bool, reason: str)
        """
        if risk_level == "HIGH":
            self.high_encounter_count += 1
            if self.high_encounter_count % 2 == 0:
                # Block on even encounters (2nd, 4th, 6th...)
                self.high_risk_blocked += 1
                return False, (
                    f"HIGH risk gated — simulated denial "
                    f"(encounter #{self.high_encounter_count}, policy: allow 50%)"
                )
            else:
                return True, (
                    f"HIGH risk allowed — simulated approval "
                    f"(encounter #{self.high_encounter_count}, policy: allow 50%)"
                )

        elif risk_level == "MEDIUM":
            self.medium_encounter_count += 1
            if self.medium_encounter_count % 5 == 0:
                # Block every 5th encounter
                self.medium_risk_blocked += 1
                return False, (
                    f"MEDIUM risk gated — simulated denial "
                    f"(encounter #{self.medium_encounter_count}, policy: allow 80%)"
                )
            else:
                return True, (
                    f"MEDIUM risk allowed — simulated approval "
                    f"(encounter #{self.medium_encounter_count}, policy: allow 80%)"
                )

        else:  # LOW
            return True, "LOW risk — always allowed"

    def get_stats(self):
        return {
            "total_scored": self.total_scored,
            "high_risk_actions": self.high_risk_actions,
            "high_risk_blocked": self.high_risk_blocked,
            "medium_risk_actions": self.medium_risk_actions,
            "medium_risk_blocked": self.medium_risk_blocked,
            "low_risk_actions": self.low_risk_actions,
        }


# ═══════════════════════════════════════════════════════════════
#  Task Selector
# ═══════════════════════════════════════════════════════════════

def select_forum_task():
    """Select a single forum/reddit task from test.raw.json."""
    with open(CONFIG_FILE) as f:
        all_tasks = json.load(f)

    reddit_tasks = [t for t in all_tasks if "reddit" in t.get("sites", [])]
    if not reddit_tasks:
        raise RuntimeError("No reddit/forum tasks found in config")

    forum_nav = [t for t in reddit_tasks if "forum" in t["intent"].lower()]
    if forum_nav:
        task = forum_nav[0]
    else:
        task = reddit_tasks[0]

    task["start_url"] = FORUM_URL
    task["storage_state"] = None
    task["require_login"] = False
    return task


# ═══════════════════════════════════════════════════════════════
#  Accessibility Tree Parser
# ═══════════════════════════════════════════════════════════════

def parse_a11y_tree(tree_text):
    """Parse accessibility tree text into structured elements."""
    elements = []
    for line in tree_text.split("\n"):
        stripped = line.strip()
        if not stripped:
            continue
        m = re.match(r".*?\[(\S+)\]\s+(\S+)\s+(.*)", stripped)
        if m:
            elem_id = m.group(1)
            role = m.group(2)
            rest = m.group(3).strip()
            name_match = re.match(r"['\"](.+?)['\"]", rest)
            name = name_match.group(1) if name_match else rest
            elements.append({
                "id": elem_id,
                "role": role,
                "name": name,
                "line": stripped,
            })
    return elements


def find_element(elements, text_match=None, role_match=None):
    """Find first element matching criteria (case-insensitive)."""
    for elem in elements:
        if role_match and role_match.lower() not in elem["role"].lower():
            continue
        if text_match and text_match.lower() not in elem["name"].lower():
            continue
        return elem
    return None


def find_clickable_elements(elements):
    """Return elements that are likely clickable (links, buttons)."""
    clickable_roles = {"link", "button", "menuitem", "tab", "searchbox", "textbox"}
    return [e for e in elements if e["role"].lower() in clickable_roles]


# ═══════════════════════════════════════════════════════════════
#  Heuristic Policy
# ═══════════════════════════════════════════════════════════════

def _is_clickable_element(elem):
    clickable_roles = {"link", "button", "menuitem", "tab", "searchbox", "textbox"}
    return elem["role"].lower() in clickable_roles


def _word_match(word, text):
    return bool(re.search(r'\b' + re.escape(word) + r'\b', text, re.IGNORECASE))


def choose_action(instruction, elements, step_num, skip_names=None):
    """Deterministic heuristic policy.

    Navigation cycle designed to hit LOW, MEDIUM, and HIGH risk
    elements so the RiskScorer + Gate can demonstrate all tiers.

    Cycle (7 targets, repeats every 7 steps):
        0: Forums       → LOW
        1: Log in link   → HIGH ("Log in" matches high-risk keywords?
                           No — "Log in" ≠ "log out". It's actually LOW.
                           But on the login PAGE, the "Log in" BUTTON
                           is HIGH because "submit" is implied.)
        2: Wiki          → LOW
        3: Sign up link  → HIGH ("sign up" matches HIGH keywords)
        4: Comments      → LOW
        5: Filter button → MEDIUM ("filter" matches MEDIUM keywords)
        6: Sort button   → MEDIUM ("sort" matches MEDIUM keywords)
    """
    if skip_names is None:
        skip_names = set()

    inst_lower = instruction.lower()
    clickable = [
        e for e in elements
        if _is_clickable_element(e) and e["name"] not in skip_names
    ]

    # Navigation cycle — 7 targets to exercise all risk tiers
    nav_targets = [
        "Forums",             # step 0, 7, 14  → LOW
        "Log in",             # step 1, 8       → HIGH (keyword match)
        "Wiki",               # step 2, 9       → LOW
        "Sign up",            # step 3, 10      → HIGH (keyword match)
        "Comments",           # step 4, 11      → LOW
        "Filter on",          # step 5, 12      → MEDIUM ("filter")
        "Sort by",            # step 6, 13      → MEDIUM ("sort")
    ]

    strategy_idx = step_num % len(nav_targets)
    target_text = nav_targets[strategy_idx]

    # Try to find the navigation target among clickable elements
    target = None
    for elem in clickable:
        if target_text.lower() in elem["name"].lower():
            target = elem
            break

    # ── Fallback: keyword-based rules ──
    if not target:
        if "login" in inst_lower or "log in" in inst_lower:
            for elem in clickable:
                if "log in" in elem["name"].lower() or "login" in elem["name"].lower():
                    target = elem
                    break

        if not target and "search" in inst_lower:
            for elem in elements:
                if (elem["role"].lower() in ("searchbox", "textbox")
                        and "search" in elem["name"].lower()
                        and elem["name"] not in skip_names):
                    search_term = "test search"
                    action = create_type_action(
                        text=search_term,
                        element_id=elem["id"],
                    )
                    return action, f"type '{search_term}' into [{elem['id']}] '{elem['name']}'"

        if not target and (_word_match("submit", inst_lower) or _word_match("post", inst_lower)):
            for elem in clickable:
                if _word_match("submit", elem["name"]) or _word_match("post", elem["name"]):
                    target = elem
                    break

    # ── Final fallback ──
    if not target:
        for elem in clickable:
            name = elem["name"].strip().strip("'\"")
            if name and name not in ("", "''", '""'):
                target = elem
                break

    if not target and clickable:
        target = clickable[0]

    if not target:
        return create_scroll_action("down"), "scroll down (no valid clickable elements)"

    return _make_click(target), f"click [{target['id']}] {target['role']} '{target['name']}'"


def _make_click(element):
    return create_click_action(element_id=element["id"])


# ═══════════════════════════════════════════════════════════════
#  Main Runner
# ═══════════════════════════════════════════════════════════════

def main():
    print("=" * 70)
    print("  SAFE RUNNER — Agent + Verifier + RiskScorer Gate")
    print("=" * 70)

    # ── Select task ──
    task = select_forum_task()
    instruction = task["intent"]
    start_url = task["start_url"]

    print(f"\n📋 Task ID:      {task['task_id']}")
    print(f"📝 Instruction:  {instruction}")
    print(f"🌐 Start URL:    {start_url}")
    print(f"🔐 Login needed: {task.get('require_login', False)}")
    print()

    # ── Temp config ──
    config_path = os.path.join(PROJECT_ROOT, "_temp_task_config.json")
    config_data = {
        "start_url": start_url,
        "storage_state": task.get("storage_state"),
        "geolocation": task.get("geolocation"),
    }
    config_data = {k: v for k, v in config_data.items() if v is not None}
    with open(config_path, "w") as f:
        json.dump(config_data, f)

    # ── Create environment + verifier + risk scorer ──
    print("🚀 Creating ScriptBrowserEnv...")
    env = ScriptBrowserEnv(
        headless=False,
        observation_type="accessibility_tree",
        current_viewport_only=True,
        viewport_size={"width": 1280, "height": 720},
        sleep_after_execution=0.5,
    )
    verifier = Verifier()
    scorer = RiskScorer()

    try:
        # ── Reset environment ──
        print("🔄 Resetting environment (opening browser)...")
        obs, info = env.reset(options={"config_file": config_path})
        current_url = info["page"].url
        verifier.prev_url = current_url
        print(f"   Page loaded: {current_url}")

        # ── Counters ──
        total_reward = 0.0
        done = False
        total_actions_proposed = 0
        total_actions_executed = 0

        for step in range(MAX_STEPS):
            print(f"\n{'─' * 60}")
            print(f"  STEP {step + 1}/{MAX_STEPS}")
            print(f"{'─' * 60}")

            # Get current observation
            tree_text = obs.get("text", "")
            print(f"\n🌳 Accessibility tree (first 800 chars):")
            print(tree_text[:800])
            if len(tree_text) > 800:
                print(f"   ... ({len(tree_text)} total chars)")

            # Parse tree
            elements = parse_a11y_tree(tree_text)
            clickable_count = len(find_clickable_elements(elements))
            print(f"\n   Parsed {len(elements)} elements, {clickable_count} clickable")

            current_url = info["page"].url

            # ═══════════════════════════════════════════════════
            #  Action Selection → Verify → Risk Score → Gate
            # ═══════════════════════════════════════════════════
            skip_names = set()
            max_retries = 8  # more retries since we now have 2 blocking layers
            action = None
            description = ""
            blocked_log = []
            action_accepted = False

            for attempt in range(max_retries):
                total_actions_proposed += 1

                # ── 1. Choose action ──
                try:
                    action, description = choose_action(
                        instruction, elements, step, skip_names
                    )
                except Exception as e:
                    print(f"   ⚠️  Action selection error: {e}")
                    action = create_none_action()
                    description = "none (error fallback)"
                    action_accepted = True
                    break

                # Resolve element text for risk scoring
                element_id = action.get("element_id", "")
                elem = Verifier._find_elem_by_id(elements, element_id) if element_id else None
                element_text = elem["name"] if elem else ""

                print(f"\n   🎯 Proposed: {description}")

                # ── 2. Verifier check ──
                v_result = verifier.validate(action, elements, current_url)

                if not v_result.valid:
                    blocked_log.append((
                        description, f"Verifier: {v_result.reason}"
                    ))
                    print(f"   🚫 BLOCKED (Verifier): {v_result.reason}")
                    if element_id and elem:
                        skip_names.add(elem["name"])
                    if attempt == max_retries - 1:
                        action = create_scroll_action("down")
                        description = "scroll down (all alternatives blocked)"
                        action_accepted = True
                        print(f"   🔄 Fallback: {description}")
                    continue

                print(f"   ✅ Verifier: PASS")

                # ── 3. Risk scoring ──
                risk_level = scorer.score(action, element_text, current_url)

                # ── 4. Tiered autonomy gate ──
                gate_allowed, gate_reason = scorer.gate(risk_level)

                if gate_allowed:
                    print(f"   🛡️  Risk: {risk_level} — {gate_reason}")
                    action_accepted = True
                    break
                else:
                    # GATED — blocked by risk gate
                    blocked_log.append((
                        description, f"Gate ({risk_level}): {gate_reason}"
                    ))
                    print(f"   🚨 GATED: [{risk_level}] {element_text}")
                    print(f"      Reason: {gate_reason}")
                    if element_id and elem:
                        skip_names.add(elem["name"])
                    if attempt == max_retries - 1:
                        action = create_scroll_action("down")
                        description = "scroll down (all alternatives gated)"
                        action_accepted = True
                        print(f"   🔄 Fallback: {description}")
                    continue

            # Log blocked/gated summary
            if blocked_log:
                print(f"\n   📋 Blocked/Gated {len(blocked_log)} action(s) before proceeding:")
                for i, (desc, reason) in enumerate(blocked_log):
                    print(f"      {i+1}. {desc} → {reason}")

            # ── Record + Execute ──
            verifier.record_action(action, current_url, elements)
            total_actions_executed += 1

            prev_url = current_url
            try:
                obs, reward, terminated, truncated, info = env.step(action)
                done = terminated or truncated
                total_reward += reward
            except Exception as e:
                print(f"   ❌ Step execution error: {e}")
                traceback.print_exc()
                try:
                    obs = env._get_obs()
                    reward = 0.0
                    done = False
                    info = {"page": type("P", (), {"url": prev_url})()}
                except Exception:
                    print("   💀 Could not recover. Breaking loop.")
                    break
                continue

            new_url = info["page"].url
            print(f"   📊 Reward: {reward}")
            print(f"   🏁 Done: {done}")
            print(f"   🔗 URL: {new_url}")
            if info.get("fail_error"):
                print(f"   ⚠️  Error: {info['fail_error']}")

            # (C) State Change Detection
            noop_msg = verifier.detect_state_change(prev_url, new_url, action, elements)
            if noop_msg:
                print(f"   ⚠️  {noop_msg}")

            if done:
                print(f"\n✅ Task marked as done after {step + 1} steps!")
                break

            time.sleep(0.3)

        # ═══════════════════════════════════════════════════════
        #  Summary
        # ═══════════════════════════════════════════════════════
        v_stats = verifier.get_stats()
        r_stats = scorer.get_stats()

        print(f"\n{'═' * 70}")
        print(f"  RUN SUMMARY")
        print(f"{'═' * 70}")
        print(f"  Steps executed:      {min(step + 1, MAX_STEPS)}")
        print(f"  Total reward:        {total_reward}")
        print(f"  Task completed:      {done}")
        print(f"  Final URL:           {info['page'].url}")
        print(f"  Actions proposed:    {total_actions_proposed}")
        print(f"  Actions executed:    {total_actions_executed}")

        print(f"{'─' * 70}")
        print(f"  VERIFIER STATS")
        print(f"{'─' * 70}")
        print(f"  Verifier proposed:   {v_stats['total_proposed']}")
        print(f"  Verifier blocked:    {v_stats['total_blocked']}")
        print(f"  No-ops detected:     {v_stats['total_noops']}")
        print(f"  History size:        {v_stats['history_len']}")

        print(f"{'─' * 70}")
        print(f"  RISK SCORER STATS")
        print(f"{'─' * 70}")
        print(f"  Total scored:        {r_stats['total_scored']}")
        print(f"  HIGH risk actions:   {r_stats['high_risk_actions']}")
        print(f"  HIGH risk blocked:   {r_stats['high_risk_blocked']}")
        print(f"  MEDIUM risk actions: {r_stats['medium_risk_actions']}")
        print(f"  MEDIUM risk blocked: {r_stats['medium_risk_blocked']}")
        print(f"  LOW risk actions:    {r_stats['low_risk_actions']}")
        print(f"{'═' * 70}")

    except Exception as e:
        print(f"\n💥 Fatal error: {e}")
        traceback.print_exc()

    finally:
        print("\n🧹 Closing browser...")
        try:
            env.close()
            print("   Browser closed cleanly.")
        except Exception as e:
            print(f"   Warning during close: {e}")

        if os.path.exists(config_path):
            os.remove(config_path)

    print("\n✅ safe_runner.py finished.\n")


if __name__ == "__main__":
    main()
