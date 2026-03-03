"""
Phase 2 — LLM Experiment Runner (Click + Structured TYPE).

Multi-domain evaluation: Forum (Postmill) + GitLab CE.

Three modes:
    A) baseline_llm_phase2       — LLM policy only, no safety layers
    B) verifier_llm_phase2       — LLM + Verifier (risk scored for tracking)
    C) verifier_gate_llm_phase2  — LLM + Verifier + RiskScorer Gate

Usage:
    python experiment_runner_llm_phase2.py
"""

import csv
import json
import os
import sys
import time
import traceback
from dataclasses import dataclass

# ── Import safe_runner (sets env vars + sys.path) ──
import safe_runner
from safe_runner import (
    Verifier,
    VerifyResult,
    RiskScorer,
    parse_a11y_tree,
    find_clickable_elements,
    FORUM_URL,
    PROJECT_ROOT,
    CONFIG_FILE,
)

# Override GITLAB env var for GitLab domain
GITLAB_URL = "http://localhost:8023"
os.environ["GITLAB"] = GITLAB_URL
GITLAB_USER = "root"
GITLAB_PASS = "Kite$7v_Mango!Q2-Quartz"

# ── Phase 2 imports ──
from type_support import find_typeable_elements, resolve_slot
from llm_policy_phase2 import choose_action_phase2

# ── Browser env (safe_runner added to sys.path) ──
from browser_env import ScriptBrowserEnv
from browser_env.actions import (
    ActionTypes,
    create_click_action,
    create_type_action,
    create_goto_url_action,
    create_scroll_action,
    create_none_action,
)

# ═══════════════════════════════════════════════════════════════
#  Config
# ═══════════════════════════════════════════════════════════════
MAX_STEPS = 12
NUM_FORUM_TASKS = 30
NUM_GITLAB_TASKS = 15
MODES = [
    "baseline_llm_phase2",
    "verifier_llm_phase2",
    "verifier_gate_llm_phase2",
]
RESULTS_FILE = os.path.join(PROJECT_ROOT, "results_llm_phase2.csv")


# ═══════════════════════════════════════════════════════════════
#  Per-Task Result
# ═══════════════════════════════════════════════════════════════
@dataclass
class TaskResult:
    mode: str
    domain: str
    task_id: int
    steps_taken: int = 0
    reward_total: float = 0.0
    unique_urls: int = 0
    actions_proposed: int = 0
    actions_executed: int = 0
    actions_blocked_verifier: int = 0
    actions_blocked_gate: int = 0
    loop_count: int = 0
    high_risk_count: int = 0
    medium_risk_count: int = 0
    low_risk_count: int = 0
    avg_llm_latency: float = 0.0
    new_page_rate: float = 0.0
    max_same_url_streak: int = 0
    # Phase 2 specific
    click_count: int = 0
    type_count: int = 0
    submission_attempts: int = 0
    gated_submission_attempts: int = 0
    error: str = ""


# ═══════════════════════════════════════════════════════════════
#  Task Loaders (reused from Phase 1)
# ═══════════════════════════════════════════════════════════════
def load_forum_tasks(n):
    with open(CONFIG_FILE) as f:
        all_tasks = json.load(f)
    reddit_tasks = [t for t in all_tasks if "reddit" in t.get("sites", [])]
    if not reddit_tasks:
        raise RuntimeError("No reddit/forum tasks found in config")
    tasks = []
    for i in range(n):
        task = dict(reddit_tasks[i % len(reddit_tasks)])
        task["start_url"] = FORUM_URL
        task["storage_state"] = None
        task["require_login"] = False
        task["_domain"] = "forum"
        tasks.append(task)
    return tasks


def load_gitlab_tasks(n):
    with open(CONFIG_FILE) as f:
        all_tasks = json.load(f)
    gitlab_tasks = [t for t in all_tasks if "gitlab" in t.get("sites", [])]
    if not gitlab_tasks:
        raise RuntimeError("No gitlab tasks found in config")
    tasks = []
    for i in range(n):
        task = dict(gitlab_tasks[i % len(gitlab_tasks)])
        raw_url = task.get("start_url", "__GITLAB__")
        task["start_url"] = raw_url.replace("__GITLAB__", GITLAB_URL)
        task["storage_state"] = None
        task["require_login"] = False
        task["_domain"] = "gitlab"
        tasks.append(task)
    return tasks


# ═══════════════════════════════════════════════════════════════
#  GitLab Login Helper (reused from Phase 1)
# ═══════════════════════════════════════════════════════════════
def gitlab_login(env, obs, info):
    action = create_goto_url_action(GITLAB_URL + "/users/sign_in")
    obs, _, _, _, info = env.step(action)
    time.sleep(1.0)

    tree_text = obs.get("text", "")
    elements = parse_a11y_tree(tree_text)

    user_field = None
    pass_field = None
    sign_in_btn = None
    for el in elements:
        name_lower = el["name"].lower()
        role_lower = el["role"].lower()
        if role_lower in ("textbox", "searchbox"):
            if "username" in name_lower or "email" in name_lower:
                user_field = el
            elif "password" in name_lower:
                pass_field = el
        if role_lower in ("button", "link") and "sign in" in name_lower and "register" not in name_lower:
            sign_in_btn = el

    if user_field:
        action = create_type_action(text=GITLAB_USER, element_id=user_field["id"])
        obs, _, _, _, info = env.step(action)
        time.sleep(0.3)
    if pass_field:
        action = create_type_action(text=GITLAB_PASS, element_id=pass_field["id"])
        obs, _, _, _, info = env.step(action)
        time.sleep(0.3)
    if sign_in_btn:
        action = create_click_action(element_id=sign_in_btn["id"])
        obs, _, _, _, info = env.step(action)
        time.sleep(1.5)

    return obs, info


# ═══════════════════════════════════════════════════════════════
#  Submission Detection
# ═══════════════════════════════════════════════════════════════
SUBMISSION_KEYWORDS = {"submit", "confirm", "create", "save", "apply", "merge"}


def is_submission_click(elem_name):
    """Check if a click targets a submission-like button."""
    text_lower = elem_name.lower()
    return any(kw in text_lower for kw in SUBMISSION_KEYWORDS)


# ═══════════════════════════════════════════════════════════════
#  Risk Scoring Helper
# ═══════════════════════════════════════════════════════════════
def _score_and_count(scorer_or_none, action, elem_name, current_url, res):
    """Score risk and update counters.  Returns risk_level string."""
    s = scorer_or_none or RiskScorer()
    risk_level = s.score(action, elem_name, current_url)
    if risk_level == "HIGH":
        res.high_risk_count += 1
    elif risk_level == "MEDIUM":
        res.medium_risk_count += 1
    else:
        res.low_risk_count += 1
    return risk_level


# ═══════════════════════════════════════════════════════════════
#  Single-Task Runner
# ═══════════════════════════════════════════════════════════════
def run_single_task(env, task, mode, config_path, verbose=False):
    """Run one task with Phase 2 LLM policy under the specified mode."""
    instruction = task["intent"]
    domain = task.get("_domain", "forum")
    res = TaskResult(mode=mode, domain=domain, task_id=task["task_id"])

    urls_visited = set()
    url_history = []
    latencies = []

    try:
        obs, info = env.reset(options={"config_file": config_path})
        current_url = info["page"].url

        # ── GitLab: login + navigate ──
        if domain == "gitlab":
            obs, info = gitlab_login(env, obs, info)
            current_url = info["page"].url
            task_start = task.get("start_url", GITLAB_URL)
            if task_start and task_start != current_url:
                action = create_goto_url_action(task_start)
                try:
                    obs, _, _, _, info = env.step(action)
                    time.sleep(0.5)
                    current_url = info["page"].url
                except Exception:
                    pass

        urls_visited.add(current_url)
        url_history.append(current_url)

        verifier = Verifier() if mode in (
            "verifier_llm_phase2", "verifier_gate_llm_phase2"
        ) else None
        scorer = RiskScorer() if mode == "verifier_gate_llm_phase2" else None

        if verifier:
            verifier.prev_url = current_url

        done = False
        for step in range(MAX_STEPS):
            tree_text = obs.get("text", "")
            elements = parse_a11y_tree(tree_text)
            current_url = info["page"].url
            clickable = find_clickable_elements(elements)
            typeable = find_typeable_elements(elements)

            if not clickable and not typeable:
                action = create_scroll_action("down")
                desc = "scroll (no interactable)"
                risk_level = "LOW"
                latency = 0.0
            else:
                # ── Phase 2 LLM chooses action ──
                max_retries = 5
                action = None
                desc = ""
                risk_level = ""
                latency = 0.0
                skip_ids = set()

                for attempt in range(max_retries):
                    res.actions_proposed += 1

                    # Filter skipped elements
                    avail_click = [e for e in clickable if e["id"] not in skip_ids]
                    avail_type = [e for e in typeable if e["id"] not in skip_ids]
                    if not avail_click and not avail_type:
                        avail_click = clickable
                        avail_type = typeable

                    llm_result = choose_action_phase2(
                        instruction, current_url, avail_click, avail_type,
                    )
                    latency = llm_result["latency"]
                    latencies.append(latency)

                    elem_id = llm_result["id"]
                    elem_name = llm_result.get("name", "")
                    elem_role = llm_result.get("role", "")
                    action_type = llm_result["type"]   # "CLICK" or "TYPE"
                    slot_name = llm_result.get("slot")  # None for CLICK

                    if not elem_id:
                        action = create_scroll_action("down")
                        desc = "scroll (no element)"
                        risk_level = "LOW"
                        break

                    # ── Build action ──
                    if action_type == "TYPE" and slot_name:
                        try:
                            slot_value = resolve_slot(slot_name)
                        except ValueError:
                            # Unknown slot → fall back to click
                            action = create_click_action(element_id=elem_id)
                            desc = f"click [{elem_id}] {elem_role} '{elem_name}' (bad slot)"
                            action_type = "CLICK"
                            slot_name = None
                        else:
                            action = create_type_action(
                                text=slot_value, element_id=elem_id,
                            )
                            desc = (f"type [{elem_id}] {elem_role} "
                                    f"'{elem_name}' ← {slot_name}")
                    else:
                        action = create_click_action(element_id=elem_id)
                        desc = f"click [{elem_id}] {elem_role} '{elem_name}'"
                        action_type = "CLICK"
                        slot_name = None

                    # ── Track submission attempts ──
                    if action_type == "CLICK" and is_submission_click(elem_name):
                        res.submission_attempts += 1

                    # ── Baseline: score but don't gate ──
                    if mode == "baseline_llm_phase2":
                        # Phase 2: Baseline risk instrumentation (no gating)
                        risk_level = _score_and_count(
                            None, action, elem_name, current_url, res,
                        )
                        risk_level = "N/A"
                        break

                    # ── Verifier ──
                    v_result = verifier.validate(action, elements, current_url)
                    if not v_result.valid:
                        res.actions_blocked_verifier += 1
                        skip_ids.add(elem_id)
                        if verbose:
                            print(f"      ⛔ Verifier: {v_result.reason[:60]}")
                        if attempt == max_retries - 1:
                            action = create_scroll_action("down")
                            desc = "scroll (verifier exhausted)"
                            risk_level = "LOW"
                        continue

                    # ── RiskScorer + Gate ──
                    if mode == "verifier_gate_llm_phase2" and scorer:
                        risk_level = _score_and_count(
                            scorer, action, elem_name, current_url, res,
                        )

                        # Track gated submissions
                        if (action_type == "CLICK"
                                and is_submission_click(elem_name)
                                and risk_level == "HIGH"):
                            pass  # submission_attempts already counted above

                        allowed, gate_reason = scorer.gate(risk_level)
                        if not allowed:
                            res.actions_blocked_gate += 1
                            # Track gated submission specifically
                            if (action_type == "CLICK"
                                    and is_submission_click(elem_name)):
                                res.gated_submission_attempts += 1
                            skip_ids.add(elem_id)
                            if verbose:
                                print(f"      🚫 Gate: {gate_reason[:60]}")
                            if attempt == max_retries - 1:
                                action = create_scroll_action("down")
                                desc = "scroll (gate exhausted)"
                                risk_level = "LOW"
                            continue

                    elif mode == "verifier_llm_phase2":
                        # Score for tracking only (no gating)
                        risk_level = _score_and_count(
                            None, action, elem_name, current_url, res,
                        )

                    break  # accepted

            # ── Record ──
            if verifier and action:
                verifier.record_action(action, current_url, elements)

            # ── Count action type ──
            if action and hasattr(action, "get"):
                at = action.get("action_type")
            elif action and isinstance(action, dict):
                at = action.get("action_type")
            else:
                at = None

            if at == ActionTypes.TYPE:
                res.type_count += 1
            elif at == ActionTypes.CLICK:
                res.click_count += 1

            res.actions_executed += 1

            if verbose:
                a_label = "TYPE" if (at == ActionTypes.TYPE) else "CLK "
                print(f"    Step {step+1:>2}/{MAX_STEPS} │ "
                      f"[{domain:>6}] "
                      f"URL={current_url[:40]:<40} │ "
                      f"{a_label} {desc[:35]:<35} │ "
                      f"Risk={risk_level:<6} │ "
                      f"LLM={latency:.2f}s")

            # ── Execute ──
            prev_url = current_url
            try:
                obs, reward, terminated, truncated, info = env.step(action)
                done = terminated or truncated
                res.reward_total += reward
            except Exception as e:
                try:
                    obs = env._get_obs()
                    info = {"page": type("P", (), {"url": prev_url})()}
                    done = False
                except Exception:
                    res.error = str(e)[:80]
                    break
                continue

            new_url = info["page"].url
            urls_visited.add(new_url)
            url_history.append(new_url)

            if verifier:
                verifier.detect_state_change(prev_url, new_url, action, elements)

            res.steps_taken = step + 1
            if done:
                break

        # ── Post-episode metrics ──
        for i in range(1, len(url_history)):
            if url_history[i] == url_history[i - 1]:
                res.loop_count += 1

        res.unique_urls = len(urls_visited)
        res.avg_llm_latency = sum(latencies) / max(len(latencies), 1)
        if res.steps_taken == 0:
            res.steps_taken = MAX_STEPS

        # new_page_rate
        if len(url_history) > 1:
            url_changes = sum(1 for i in range(1, len(url_history))
                              if url_history[i] != url_history[i - 1])
            res.new_page_rate = round(url_changes / max(res.steps_taken, 1), 3)
        else:
            res.new_page_rate = 0.0

        # max_same_url_streak
        if url_history:
            streak = 1
            max_streak = 1
            for i in range(1, len(url_history)):
                if url_history[i] == url_history[i - 1]:
                    streak += 1
                    if streak > max_streak:
                        max_streak = streak
                else:
                    streak = 1
            res.max_same_url_streak = max_streak
        else:
            res.max_same_url_streak = 0

    except Exception as e:
        res.error = str(e)[:80]

    return res


# ═══════════════════════════════════════════════════════════════
#  Validation Pass
# ═══════════════════════════════════════════════════════════════
def run_validation(forum_tasks, gitlab_tasks):
    print("\n" + "=" * 74)
    print("  PHASE 2 VALIDATION — 1 forum + 1 gitlab task, baseline")
    print("=" * 74)

    global MAX_STEPS
    orig = MAX_STEPS
    MAX_STEPS = 5

    for label, tasks, start_url in [
        ("FORUM", forum_tasks, FORUM_URL),
        ("GITLAB", gitlab_tasks, GITLAB_URL),
    ]:
        task = tasks[0]
        print(f"\n  [{label}] Task ID={task['task_id']}: {task['intent'][:60]}")

        config_path = os.path.join(PROJECT_ROOT, f"_temp_val_p2_{label.lower()}.json")
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
            result = run_single_task(
                env, task, "baseline_llm_phase2", config_path, verbose=True,
            )
            print(f"\n  Result: steps={result.steps_taken} "
                  f"reward={result.reward_total:.1f} "
                  f"urls={result.unique_urls} "
                  f"clicks={result.click_count} "
                  f"types={result.type_count} "
                  f"latency={result.avg_llm_latency:.2f}s "
                  f"error={'None' if not result.error else result.error}")
            if result.error:
                print(f"  ❌ {label} validation FAILED: {result.error}")
                MAX_STEPS = orig
                return False
            print(f"  ✅ {label} validation PASSED")
        finally:
            try:
                env.close()
            except Exception:
                pass
            if os.path.exists(config_path):
                os.remove(config_path)

    MAX_STEPS = orig
    print("\n  ✅ Both domains validated — proceeding to Phase 2 experiment")
    return True


# ═══════════════════════════════════════════════════════════════
#  Full Experiment
# ═══════════════════════════════════════════════════════════════
def run_experiment():
    total_start = time.time()
    total_tasks = NUM_FORUM_TASKS + NUM_GITLAB_TASKS

    print("=" * 80)
    print("  PHASE 2 LLM EXPERIMENT — Click + Structured TYPE (Ollama qwen3:8b)")
    print("=" * 80)
    print(f"  Modes:        {', '.join(MODES)}")
    print(f"  Forum tasks:  {NUM_FORUM_TASKS}")
    print(f"  GitLab tasks: {NUM_GITLAB_TASKS}")
    print(f"  Total/mode:   {total_tasks}")
    print(f"  Steps/task:   {MAX_STEPS}")
    print(f"  Model:        qwen3:8b (temp=0.7)")
    print(f"  Output:       {RESULTS_FILE}")
    print("=" * 80)

    forum_tasks = load_forum_tasks(NUM_FORUM_TASKS)
    gitlab_tasks = load_gitlab_tasks(NUM_GITLAB_TASKS)
    all_tasks = forum_tasks + gitlab_tasks

    f_ids = len(set(t["task_id"] for t in forum_tasks))
    g_ids = len(set(t["task_id"] for t in gitlab_tasks))
    print(f"\n📋 Forum: {len(forum_tasks)} tasks ({f_ids} unique)")
    print(f"📋 GitLab: {len(gitlab_tasks)} tasks ({g_ids} unique)")

    # ── Validation pass ──
    ok = run_validation(forum_tasks, gitlab_tasks)
    if not ok:
        print("Aborting.")
        return

    # ── Config files per domain ──
    forum_config = os.path.join(PROJECT_ROOT, "_temp_p2_forum.json")
    gitlab_config = os.path.join(PROJECT_ROOT, "_temp_p2_gitlab.json")
    with open(forum_config, "w") as f:
        json.dump({"start_url": FORUM_URL}, f)
    with open(gitlab_config, "w") as f:
        json.dump({"start_url": GITLAB_URL}, f)

    # ── Full run ──
    all_results = []

    for mode in MODES:
        print(f"\n{'━' * 80}")
        print(f"  MODE: {mode.upper()}")
        print(f"{'━' * 80}")

        env = ScriptBrowserEnv(
            headless=False,
            observation_type="accessibility_tree",
            current_viewport_only=True,
            viewport_size={"width": 1280, "height": 720},
            sleep_after_execution=0.3,
        )

        mode_start = time.time()

        try:
            for i, task in enumerate(all_tasks):
                t0 = time.time()
                domain = task.get("_domain", "forum")
                config_path = gitlab_config if domain == "gitlab" else forum_config

                tag = "GL" if domain == "gitlab" else "FM"
                label = f"[{mode}] {tag} {i+1:>2}/{total_tasks} (id={task['task_id']:<4})"
                print(f"  {label} ...", end=" ", flush=True)

                result = run_single_task(env, task, mode, config_path)
                all_results.append(result)

                elapsed = time.time() - t0
                flag = "✅" if not result.error else f"⚠️  {result.error[:25]}"
                print(
                    f"{flag} {elapsed:5.1f}s │ "
                    f"steps={result.steps_taken:>2} "
                    f"rew={result.reward_total:>5.1f} "
                    f"urls={result.unique_urls:>2} "
                    f"V={result.actions_blocked_verifier:>2} "
                    f"G={result.actions_blocked_gate:>2} "
                    f"H={result.high_risk_count:>2} "
                    f"M={result.medium_risk_count:>2} "
                    f"L={result.low_risk_count:>2} "
                    f"C={result.click_count:>2} "
                    f"T={result.type_count:>2} "
                    f"sub={result.submission_attempts:>1} "
                    f"lat={result.avg_llm_latency:.1f}s"
                )
        finally:
            try:
                env.close()
            except Exception:
                pass

        mode_elapsed = time.time() - mode_start
        print(f"\n  ⏱  Mode '{mode}' completed in {mode_elapsed:.1f}s")

    # ═══════════════════════════════════════════════════════════
    #  Save CSV
    # ═══════════════════════════════════════════════════════════
    with open(RESULTS_FILE, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            "mode", "domain", "task_id", "steps", "reward", "unique_urls",
            "blocked_verifier", "blocked_gate",
            "actions_proposed", "actions_executed", "loop_count",
            "high_risk", "medium_risk", "low_risk", "avg_llm_latency",
            "new_page_rate", "max_same_url_streak",
            "click_count", "type_count",
            "submission_attempts", "gated_submission_attempts",
        ])
        for r in all_results:
            writer.writerow([
                r.mode, r.domain, r.task_id, r.steps_taken, r.reward_total,
                r.unique_urls, r.actions_blocked_verifier,
                r.actions_blocked_gate, r.actions_proposed,
                r.actions_executed, r.loop_count,
                r.high_risk_count, r.medium_risk_count,
                r.low_risk_count, f"{r.avg_llm_latency:.3f}",
                f"{r.new_page_rate:.3f}", r.max_same_url_streak,
                r.click_count, r.type_count,
                r.submission_attempts, r.gated_submission_attempts,
            ])

    print(f"\n📄 Results saved to {RESULTS_FILE}")

    # ═══════════════════════════════════════════════════════════
    #  Aggregate Summary Table
    # ═══════════════════════════════════════════════════════════
    total_elapsed = time.time() - total_start

    print(f"\n{'═' * 130}")
    print(f"  AGGREGATE SUMMARY — Phase 2 by Mode × Domain")
    print(f"{'═' * 130}")

    header = (f"  {'Mode':<28} {'Dom':<6} {'N':>3} {'Steps':>5} {'Rew':>5} "
              f"{'URLs':>4} {'H':>4} {'M':>4} {'L':>4} "
              f"{'VBlk':>4} {'GBlk':>4} "
              f"{'CLK':>4} {'TYP':>4} {'Sub':>3} {'GSub':>4} "
              f"{'Lat':>6}")
    print(header)
    print("  " + "─" * 120)

    for m in MODES:
        for dom in ["forum", "gitlab"]:
            mrs = [r for r in all_results if r.mode == m and r.domain == dom]
            if not mrs:
                continue
            n = len(mrs)
            print(f"  {m:<28} {dom:<6} {n:>3} "
                  f"{sum(r.steps_taken for r in mrs)/n:>5.1f} "
                  f"{sum(r.reward_total for r in mrs)/n:>5.1f} "
                  f"{sum(r.unique_urls for r in mrs)/n:>4.1f} "
                  f"{sum(r.high_risk_count for r in mrs):>4} "
                  f"{sum(r.medium_risk_count for r in mrs):>4} "
                  f"{sum(r.low_risk_count for r in mrs):>4} "
                  f"{sum(r.actions_blocked_verifier for r in mrs):>4} "
                  f"{sum(r.actions_blocked_gate for r in mrs):>4} "
                  f"{sum(r.click_count for r in mrs):>4} "
                  f"{sum(r.type_count for r in mrs):>4} "
                  f"{sum(r.submission_attempts for r in mrs):>3} "
                  f"{sum(r.gated_submission_attempts for r in mrs):>4} "
                  f"{sum(r.avg_llm_latency for r in mrs)/n:>5.2f}s")

    print("  " + "─" * 120)
    for m in MODES:
        mrs = [r for r in all_results if r.mode == m]
        if not mrs:
            continue
        n = len(mrs)
        print(f"  {m:<28} {'ALL':<6} {n:>3} "
              f"{sum(r.steps_taken for r in mrs)/n:>5.1f} "
              f"{sum(r.reward_total for r in mrs)/n:>5.1f} "
              f"{sum(r.unique_urls for r in mrs)/n:>4.1f} "
              f"{sum(r.high_risk_count for r in mrs):>4} "
              f"{sum(r.medium_risk_count for r in mrs):>4} "
              f"{sum(r.low_risk_count for r in mrs):>4} "
              f"{sum(r.actions_blocked_verifier for r in mrs):>4} "
              f"{sum(r.actions_blocked_gate for r in mrs):>4} "
              f"{sum(r.click_count for r in mrs):>4} "
              f"{sum(r.type_count for r in mrs):>4} "
              f"{sum(r.submission_attempts for r in mrs):>3} "
              f"{sum(r.gated_submission_attempts for r in mrs):>4} "
              f"{sum(r.avg_llm_latency for r in mrs)/n:>5.2f}s")

    print(f"\n  ⏱  Total runtime: {total_elapsed:.1f}s ({total_elapsed/60:.1f} min)")

    # Cleanup
    for p in [forum_config, gitlab_config]:
        if os.path.exists(p):
            os.remove(p)

    # ═══════════════════════════════════════════════════════════
    #  Phase 2 Final Banner
    # ═══════════════════════════════════════════════════════════
    print()
    print("══════════════════════════════════════════")
    print("PHASE 2 — STRUCTURED TYPE COMPLETE")
    print("══════════════════════════════════════════")
    print("Click + Type enabled")
    print("Submission remains gated")
    print(f"Total runs: {len(all_results)} (3 modes × {total_tasks} tasks)")
    print("Outputs:")
    print(f"  {RESULTS_FILE}")
    print("  reports_llm_phase2/")
    print("══════════════════════════════════════════")
    print()
    print("PHASE 2 LOCKED.")
    print("READY FOR PHASE 3.")


if __name__ == "__main__":
    run_experiment()
