"""
Phase 3B — Visual Debug Runner (Instruction-Conditioned Autonomy).

Shows PLAN, ACTION, risk, gate, and goal alignment per step.

Usage:
    python visual_debug_runner_phase3b.py
"""

import json
import os
import time

import safe_runner
from safe_runner import (
    Verifier, RiskScorer, parse_a11y_tree, find_clickable_elements,
    FORUM_URL, PROJECT_ROOT, CONFIG_FILE,
)

GITLAB_URL = "http://localhost:8023"
os.environ["GITLAB"] = GITLAB_URL
GITLAB_USER = "root"
GITLAB_PASS = "Kite$7v_Mango!Q2-Quartz"

from type_support import find_typeable_elements
from llm_policy_phase3b import choose_action_phase3b

from browser_env import ScriptBrowserEnv
from browser_env.actions import (
    create_click_action, create_type_action,
    create_goto_url_action, create_scroll_action,
)


def gitlab_login(env, obs, info):
    obs, _, _, _, info = env.step(
        create_goto_url_action(GITLAB_URL + "/users/sign_in"))
    time.sleep(1.0)
    elements = parse_a11y_tree(obs.get("text", ""))
    uf = pf = sb = None
    for el in elements:
        nl, rl = el["name"].lower(), el["role"].lower()
        if rl in ("textbox", "searchbox"):
            if "username" in nl or "email" in nl: uf = el
            elif "password" in nl: pf = el
        if rl in ("button", "link") and "sign in" in nl and "register" not in nl:
            sb = el
    if uf:
        obs, _, _, _, info = env.step(
            create_type_action(text=GITLAB_USER, element_id=uf["id"]))
        time.sleep(0.3)
    if pf:
        obs, _, _, _, info = env.step(
            create_type_action(text=GITLAB_PASS, element_id=pf["id"]))
        time.sleep(0.3)
    if sb:
        obs, _, _, _, info = env.step(
            create_click_action(element_id=sb["id"]))
        time.sleep(1.5)
    return obs, info


def main():
    MAX_STEPS = 12
    STEP_DELAY = 0.8
    DOMAIN = "forum"  # Change to "gitlab" to test GitLab

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
    print(f"  PHASE 3B VISUAL DEBUG — {DOMAIN.upper()}")
    print(f"  Task: {instruction[:70]}")
    print(f"  Mode: verifier_gate (full safety)")
    print(f"  Planning: YES")
    print(f"  Steps: {MAX_STEPS}")
    print("=" * 80)

    config_path = os.path.join(PROJECT_ROOT, "_temp_debug_p3b.json")
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
        action_history = []

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
                print("  PLAN: (none)")
                print("  ACTION: SCROLL")
                print("  Risk: LOW  Gate: N/A")
            else:
                llm_result = choose_action_phase3b(
                    instruction, current_url, clickable, typeable,
                    action_history)

                plan = llm_result.get("plan", "")
                action_type = llm_result["type"]
                elem_id = llm_result["id"]
                elem_name = llm_result.get("name", "")
                typed_text = llm_result.get("text")
                latency = llm_result["latency"]
                alignment = llm_result.get("goal_alignment", 0)

                print(f"  LLM raw: {llm_result['llm_raw'][:80]}")
                print(f"  PLAN: {plan[:70] if plan else '(none)'}")
                print(f"  Parsed: {llm_result['parsed']}  "
                      f"Latency: {latency:.2f}s  "
                      f"Align: {alignment:.3f}")

                if action_type == "TYPE" and typed_text:
                    action = create_type_action(
                        text=typed_text, element_id=elem_id)
                    print(f"  ACTION: TYPE [{elem_id}] '{elem_name}'")
                    print(f"  TEXT: \"{typed_text}\"")
                    action_history.append(
                        f"TYPE [{elem_id}] '{elem_name}' "
                        f"← \"{typed_text[:30]}\"")
                else:
                    action = create_click_action(element_id=elem_id)
                    action_type = "CLICK"
                    print(f"  ACTION: CLICK [{elem_id}] '{elem_name}'")
                    action_history.append(
                        f"CLICK [{elem_id}] '{elem_name}'")

                v_result = verifier.validate(action, elements, current_url)
                if not v_result.valid:
                    print(f"  ⛔ VERIFIER: {v_result.reason[:60]}")
                    action = create_scroll_action("down")
                    print("  Fallback: SCROLL")
                else:
                    risk_level = scorer.score(
                        action, elem_name, current_url)
                    print(f"  Risk: {risk_level}")
                    allowed, gate_reason = scorer.gate(risk_level)
                    if allowed:
                        print(f"  Gate: ✅ {gate_reason[:50]}")
                    else:
                        print(f"  Gate: 🚫 {gate_reason[:50]}")
                        action = create_scroll_action("down")
                        print("  Fallback: SCROLL")

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
                verifier.detect_state_change(
                    prev_url, new_url, action, elements)
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
