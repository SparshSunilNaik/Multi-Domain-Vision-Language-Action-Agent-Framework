"""
Phase 2 — Visual Debug Runner (Click + Structured TYPE).

Runs a single task with all safety layers active, headless=False,
and prints detailed per-step information for debugging.

Usage:
    python visual_debug_runner_phase2.py
"""

import json
import os
import time

# ── Import safe_runner (sets env vars + sys.path) ──
import safe_runner
from safe_runner import (
    Verifier,
    RiskScorer,
    parse_a11y_tree,
    find_clickable_elements,
    FORUM_URL,
    PROJECT_ROOT,
    CONFIG_FILE,
)

# GitLab config
GITLAB_URL = "http://localhost:8023"
os.environ["GITLAB"] = GITLAB_URL
GITLAB_USER = "root"
GITLAB_PASS = "Kite$7v_Mango!Q2-Quartz"

# Phase 2 imports
from type_support import find_typeable_elements, resolve_slot
from llm_policy_phase2 import choose_action_phase2

# Browser env
from browser_env import ScriptBrowserEnv
from browser_env.actions import (
    ActionTypes,
    create_click_action,
    create_type_action,
    create_goto_url_action,
    create_scroll_action,
)


# ═══════════════════════════════════════════════════════════════
#  GitLab Login helper
# ═══════════════════════════════════════════════════════════════
def gitlab_login(env, obs, info):
    action = create_goto_url_action(GITLAB_URL + "/users/sign_in")
    obs, _, _, _, info = env.step(action)
    time.sleep(1.0)

    tree_text = obs.get("text", "")
    elements = parse_a11y_tree(tree_text)
    user_field = pass_field = sign_in_btn = None
    for el in elements:
        nl = el["name"].lower()
        rl = el["role"].lower()
        if rl in ("textbox", "searchbox"):
            if "username" in nl or "email" in nl:
                user_field = el
            elif "password" in nl:
                pass_field = el
        if rl in ("button", "link") and "sign in" in nl and "register" not in nl:
            sign_in_btn = el

    if user_field:
        obs, _, _, _, info = env.step(
            create_type_action(text=GITLAB_USER, element_id=user_field["id"]))
        time.sleep(0.3)
    if pass_field:
        obs, _, _, _, info = env.step(
            create_type_action(text=GITLAB_PASS, element_id=pass_field["id"]))
        time.sleep(0.3)
    if sign_in_btn:
        obs, _, _, _, info = env.step(
            create_click_action(element_id=sign_in_btn["id"]))
        time.sleep(1.5)
    return obs, info


# ═══════════════════════════════════════════════════════════════
#  Main
# ═══════════════════════════════════════════════════════════════
def main():
    MAX_STEPS = 12
    STEP_DELAY = 0.8

    # Pick domain (change to "gitlab" to test GitLab)
    DOMAIN = "forum"

    with open(CONFIG_FILE) as f:
        all_tasks = json.load(f)

    if DOMAIN == "forum":
        tasks = [t for t in all_tasks if "reddit" in t.get("sites", [])]
        start_url = FORUM_URL
    else:
        tasks = [t for t in all_tasks if "gitlab" in t.get("sites", [])]
        start_url = GITLAB_URL

    task = dict(tasks[0])
    task["start_url"] = start_url
    task["storage_state"] = None
    task["require_login"] = False

    instruction = task["intent"]

    print("=" * 80)
    print(f"  PHASE 2 VISUAL DEBUG — {DOMAIN.upper()}")
    print(f"  Task: {instruction[:70]}")
    print(f"  Mode: verifier_gate (full safety)")
    print(f"  Steps: {MAX_STEPS}")
    print("=" * 80)

    config_path = os.path.join(PROJECT_ROOT, "_temp_debug_p2.json")
    with open(config_path, "w") as f:
        json.dump({"start_url": start_url}, f)

    env = ScriptBrowserEnv(
        headless=False,
        observation_type="accessibility_tree",
        current_viewport_only=True,
        viewport_size={"width": 1280, "height": 720},
        sleep_after_execution=0.3,
    )

    try:
        obs, info = env.reset(options={"config_file": config_path})
        current_url = info["page"].url

        if DOMAIN == "gitlab":
            obs, info = gitlab_login(env, obs, info)
            current_url = info["page"].url
            task_start = task.get("start_url", GITLAB_URL)
            if task_start.startswith("__GITLAB__"):
                task_start = task_start.replace("__GITLAB__", GITLAB_URL)
            if task_start and task_start != current_url:
                try:
                    obs, _, _, _, info = env.step(
                        create_goto_url_action(task_start))
                    time.sleep(0.5)
                    current_url = info["page"].url
                except Exception:
                    pass

        verifier = Verifier()
        scorer = RiskScorer()
        verifier.prev_url = current_url

        total_reward = 0.0

        for step in range(MAX_STEPS):
            tree_text = obs.get("text", "")
            elements = parse_a11y_tree(tree_text)
            current_url = info["page"].url
            clickable = find_clickable_elements(elements)
            typeable = find_typeable_elements(elements)

            print(f"\n{'─' * 80}")
            print(f"  Step {step+1}/{MAX_STEPS}")
            print(f"  URL: {current_url}")
            print(f"  Clickable: {len(clickable)}  Typeable: {len(typeable)}")

            if not clickable and not typeable:
                action = create_scroll_action("down")
                print("  Action: SCROLL (no interactable elements)")
                print("  Risk: LOW")
                print("  Gate: N/A")
            else:
                llm_result = choose_action_phase2(
                    instruction, current_url, clickable, typeable,
                )
                action_type = llm_result["type"]
                elem_id = llm_result["id"]
                elem_name = llm_result.get("name", "")
                slot_name = llm_result.get("slot")
                parsed = llm_result["parsed"]
                latency = llm_result["latency"]

                print(f"  LLM raw: {llm_result['llm_raw'][:60]}")
                print(f"  Parsed: {parsed}  Latency: {latency:.2f}s")

                # Build action
                if action_type == "TYPE" and slot_name:
                    try:
                        slot_value = resolve_slot(slot_name)
                    except ValueError as ve:
                        print(f"  ⚠️  Bad slot: {ve}")
                        action = create_click_action(element_id=elem_id)
                        action_type = "CLICK"
                        slot_name = None
                    else:
                        action = create_type_action(
                            text=slot_value, element_id=elem_id)
                else:
                    action = create_click_action(element_id=elem_id)
                    action_type = "CLICK"

                print(f"  Action: {action_type} [{elem_id}] '{elem_name}'",
                      end="")
                if slot_name:
                    print(f"  Slot: {slot_name} → '{resolve_slot(slot_name)}'")
                else:
                    print()

                # Verifier
                v_result = verifier.validate(action, elements, current_url)
                if not v_result.valid:
                    print(f"  ⛔ VERIFIER BLOCKED: {v_result.reason[:60]}")
                    action = create_scroll_action("down")
                    print("  Fallback: SCROLL")
                else:
                    # Risk score + gate
                    risk_level = scorer.score(action, elem_name, current_url)
                    print(f"  Risk: {risk_level}")

                    allowed, gate_reason = scorer.gate(risk_level)
                    if allowed:
                        print(f"  Gate: ✅ ALLOWED — {gate_reason[:50]}")
                    else:
                        print(f"  Gate: 🚫 BLOCKED — {gate_reason[:50]}")
                        action = create_scroll_action("down")
                        print("  Fallback: SCROLL")

            # Execute
            prev_url = current_url
            try:
                obs, reward, terminated, truncated, info = env.step(action)
                total_reward += reward
                print(f"  Reward: {reward:.1f} (total: {total_reward:.1f})")
            except Exception as e:
                print(f"  ❌ Error: {str(e)[:60]}")
                try:
                    obs = env._get_obs()
                    info = {"page": type("P", (), {"url": prev_url})()}
                except Exception:
                    break
                continue

            if verifier:
                new_url = info["page"].url
                verifier.detect_state_change(prev_url, new_url, action, elements)
                verifier.record_action(action, current_url, elements)

            time.sleep(STEP_DELAY)

            if terminated or truncated:
                print("\n  🏁 Episode terminated.")
                break

        print(f"\n{'═' * 80}")
        print(f"  DONE — Total reward: {total_reward:.1f}")
        print(f"{'═' * 80}")

    finally:
        try:
            env.close()
        except Exception:
            pass
        if os.path.exists(config_path):
            os.remove(config_path)


if __name__ == "__main__":
    main()
