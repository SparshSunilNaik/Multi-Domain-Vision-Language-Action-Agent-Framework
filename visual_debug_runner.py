"""
Interactive visual debugging runner for the Safe WebArena Agent.

Opens a visible browser window, steps slowly, and prints clean
structured logs for each action.  Supports three modes via --mode:

    baseline        raw heuristic policy, no safety layers
    verifier        heuristic + Verifier
    verifier+gate   heuristic + Verifier + RiskScorer gate  (default)

Usage:
    python visual_debug_runner.py                        # default: verifier+gate
    python visual_debug_runner.py --mode baseline
    python visual_debug_runner.py --mode verifier
    python visual_debug_runner.py --mode verifier+gate
"""

import argparse
import json
import os
import sys
import time
import traceback

# ── Import safe_runner (sets up sys.path + env vars) ──
import safe_runner
from safe_runner import (
    Verifier,
    VerifyResult,
    RiskScorer,
    choose_action,
    parse_a11y_tree,
    find_clickable_elements,
    select_forum_task,
    FORUM_URL,
    PROJECT_ROOT,
    MAX_STEPS as _ORIG_MAX_STEPS,
)

from browser_env import ScriptBrowserEnv
from browser_env.actions import (
    create_none_action,
    create_scroll_action,
)

# ═══════════════════════════════════════════════════════════════
#  Config
# ═══════════════════════════════════════════════════════════════
VISUAL_MAX_STEPS = 12
STEP_DELAY = 0.8          # seconds between executed actions
VALID_MODES = ("baseline", "verifier", "verifier+gate")

# ── Box-drawing chars for pretty output ──
TOP    = "┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓"
MID    = "┣━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┫"
BOT    = "┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛"
INNER  = 62  # inner width


def box_line(text, align="left"):
    """Return a box-bordered line."""
    if align == "center":
        content = text.center(INNER)
    else:
        content = f"  {text}".ljust(INNER)
    return f"┃{content}┃"


# ═══════════════════════════════════════════════════════════════
#  CLI
# ═══════════════════════════════════════════════════════════════
def parse_args():
    parser = argparse.ArgumentParser(
        description="Visual debug runner – opens a browser and steps slowly."
    )
    parser.add_argument(
        "--mode",
        choices=VALID_MODES,
        default="verifier+gate",
        help="Safety-layer mode (default: verifier+gate)",
    )
    return parser.parse_args()


# ═══════════════════════════════════════════════════════════════
#  Runner
# ═══════════════════════════════════════════════════════════════
def run(mode: str):
    # ── Banner ──
    print()
    print(TOP)
    print(box_line("VISUAL DEBUG RUNNER", align="center"))
    print(MID)
    print(box_line(f"Mode:       {mode}"))
    print(box_line(f"Max steps:  {VISUAL_MAX_STEPS}"))
    print(box_line(f"Step delay: {STEP_DELAY}s"))
    print(box_line(f"Headless:   False"))
    print(BOT)

    # ── Select task ──
    task = select_forum_task()
    instruction = task["intent"]
    start_url = task["start_url"]

    print(f"\n  📋 Task:  {task['task_id']}")
    print(f"  📝 Goal:  {instruction[:70]}")
    print(f"  🌐 URL:   {start_url}")

    # ── Temp config ──
    config_path = os.path.join(PROJECT_ROOT, "_temp_visual_config.json")
    with open(config_path, "w") as f:
        json.dump({"start_url": start_url}, f)

    # ── Create env (visible browser) ──
    print(f"\n  🚀 Launching visible browser …")
    env = ScriptBrowserEnv(
        headless=False,
        observation_type="accessibility_tree",
        current_viewport_only=True,
        viewport_size={"width": 1280, "height": 720},
        sleep_after_execution=0.5,
    )

    # ── Safety layers (per mode) ──
    verifier = Verifier() if mode in ("verifier", "verifier+gate") else None
    scorer   = RiskScorer() if mode == "verifier+gate" else None

    # ── Counters ──
    urls_visited = set()
    total_blocked_verifier = 0
    total_blocked_gate = 0
    total_proposed = 0
    total_executed = 0

    try:
        obs, info = env.reset(options={"config_file": config_path})
        current_url = info["page"].url
        urls_visited.add(current_url)
        if verifier:
            verifier.prev_url = current_url

        print(f"  ✅ Browser ready: {current_url}\n")

        done = False
        for step in range(VISUAL_MAX_STEPS):
            # ── Parse observation ──
            tree_text = obs.get("text", "")
            elements = parse_a11y_tree(tree_text)
            current_url = info["page"].url
            urls_visited.add(current_url)

            # ── Choose + validate ──
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
                    action, description = choose_action(
                        instruction, elements, step, skip_names
                    )
                except Exception:
                    action = create_none_action()
                    description = "none (error)"
                    verifier_status = "SKIP"
                    risk_level = "N/A"
                    gate_status = "SKIP"
                    break

                elem_id = action.get("element_id", "")
                elem = (Verifier._find_elem_by_id(elements, elem_id)
                        if elem_id else None)
                elem_text = elem["name"] if elem else ""

                # ── MODE A: baseline ──
                if mode == "baseline":
                    verifier_status = "SKIP"
                    risk_level = "N/A"
                    gate_status = "SKIP"
                    break

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
                if mode == "verifier+gate" and scorer:
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
                else:
                    risk_level = "N/A"
                    gate_status = "N/A"

                break  # accepted

            # ── Record in verifier ──
            if verifier:
                verifier.record_action(action, current_url, elements)

            total_executed += 1

            # ── Step log (BEFORE execution) ──
            print(TOP)
            print(box_line(f"STEP {step + 1}/{VISUAL_MAX_STEPS}", align="center"))
            print(MID)
            print(box_line(f"URL:       {current_url}"))
            print(box_line(f"Proposed:  {description}"))
            print(box_line(f"Verifier:  {verifier_status}"))
            print(box_line(f"Risk:      {risk_level}"))
            print(box_line(f"Gate:      {gate_status}"))

            if gate_status == "BLOCKED" or gate_status == "BLOCKED → fallback":
                print(MID)
                print(box_line(f"⚠  GATED — {gate_reason}"))
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
                    print("\n  💀 Unrecoverable error — stopping.")
                    break
                print(BOT)
                continue

            new_url = info["page"].url
            urls_visited.add(new_url)

            print(box_line(f"Reward:    {reward}"))
            print(box_line(f"Done:      {done}"))
            if new_url != current_url:
                print(box_line(f"New URL:   {new_url}"))
            print(BOT)

            # State change detection
            if verifier:
                noop = verifier.detect_state_change(
                    prev_url, new_url, action, elements
                )
                if noop:
                    print(f"  ⚠️  {noop}")

            if done:
                print(f"\n  🏁 Task done at step {step + 1}!")
                break

            # Slow-mo delay for visual observation
            time.sleep(STEP_DELAY)

        # ══════════════════════════════════════════════════════
        #  Summary
        # ══════════════════════════════════════════════════════
        final_step = min(step + 1, VISUAL_MAX_STEPS)
        print()
        print(TOP)
        print(box_line(f"SUMMARY — mode: {mode}", align="center"))
        print(MID)
        print(box_line(f"Steps:                {final_step}"))
        print(box_line(f"Actions proposed:     {total_proposed}"))
        print(box_line(f"Actions executed:     {total_executed}"))
        print(box_line(f"Blocked by verifier:  {total_blocked_verifier}"))
        print(box_line(f"Blocked by gate:      {total_blocked_gate}"))
        print(box_line(f"Unique URLs visited:  {len(urls_visited)}"))
        print(box_line(f"URLs: {', '.join(sorted(urls_visited))}"))
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


# ═══════════════════════════════════════════════════════════════
if __name__ == "__main__":
    args = parse_args()
    run(args.mode)
