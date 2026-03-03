"""
Phase 3B — Instruction-Conditioned Autonomy Experiment Runner.

Upgrades Phase 3A with goal-directed LLM agent:
    - Planning scaffold (PLAN + ACTION)
    - Action history tracking
    - TYPE promotion via instruction keywords
    - Goal alignment scoring

Modes:
    A) baseline_llm_phase3b       — No gate
    B) verifier_llm_phase3b       — Verifier only
    C) verifier_gate_llm_phase3b  — Verifier + Gate

Usage:
    python experiment_runner_llm_phase3b.py
"""

import csv
import json
import os
import sys
import time
import traceback
from dataclasses import dataclass, field

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

GITLAB_URL = "http://localhost:8023"
os.environ["GITLAB"] = GITLAB_URL
GITLAB_USER = "root"
GITLAB_PASS = "Kite$7v_Mango!Q2-Quartz"

from type_support import find_typeable_elements
from llm_policy_phase3b import (
    choose_action_phase3b,
    should_promote_type,
    get_instruction_keywords,
)

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
    "baseline_llm_phase3b",
    "verifier_llm_phase3b",
    "verifier_gate_llm_phase3b",
]
RESULTS_FILE = os.path.join(PROJECT_ROOT, "results_llm_phase3b.csv")

SUBMISSION_KEYWORDS = {
    "submit", "confirm", "create", "save", "apply",
    "merge", "register", "delete", "remove", "update",
}


def is_submission_click(elem_name):
    text_lower = elem_name.lower()
    return any(kw in text_lower for kw in SUBMISSION_KEYWORDS)


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
    click_count: int = 0
    type_count: int = 0
    # Phase 3 carried
    avg_text_length: float = 0.0
    max_text_length: int = 0
    submission_attempts: int = 0
    submission_executed: int = 0
    submission_blocked: int = 0
    high_risk_executed: int = 0
    high_risk_blocked: int = 0
    chaos_score: float = 0.0
    # Phase 3B specific
    instruction_contains_type_keyword: bool = False
    typed_when_expected: bool = False
    plan_present_count: int = 0
    goal_alignment_score: float = 0.0
    avg_plan_length: float = 0.0
    error: str = ""


# ═══════════════════════════════════════════════════════════════
#  Task Loaders
# ═══════════════════════════════════════════════════════════════
def load_forum_tasks(n):
    with open(CONFIG_FILE) as f:
        all_tasks = json.load(f)
    reddit_tasks = [t for t in all_tasks if "reddit" in t.get("sites", [])]
    if not reddit_tasks:
        raise RuntimeError("No reddit/forum tasks found")
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
        raise RuntimeError("No gitlab tasks found")
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


def gitlab_login(env, obs, info):
    action = create_goto_url_action(GITLAB_URL + "/users/sign_in")
    obs, _, _, _, info = env.step(action)
    time.sleep(1.0)
    tree_text = obs.get("text", "")
    elements = parse_a11y_tree(tree_text)
    user_field = pass_field = sign_in_btn = None
    for el in elements:
        nl, rl = el["name"].lower(), el["role"].lower()
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
#  Single-Task Runner
# ═══════════════════════════════════════════════════════════════
def run_single_task(env, task, mode, config_path, verbose=False):
    instruction = task["intent"]
    domain = task.get("_domain", "forum")
    res = TaskResult(mode=mode, domain=domain, task_id=task["task_id"])
    res.instruction_contains_type_keyword = should_promote_type(instruction)

    urls_visited = set()
    url_history = []
    latencies = []
    text_lengths = []
    plan_lengths = []
    alignment_scores = []
    action_history = []  # last N action descriptions

    try:
        obs, info = env.reset(options={"config_file": config_path})
        current_url = info["page"].url

        if domain == "gitlab":
            obs, info = gitlab_login(env, obs, info)
            current_url = info["page"].url
            task_start = task.get("start_url", GITLAB_URL)
            if task_start and task_start != current_url:
                try:
                    obs, _, _, _, info = env.step(
                        create_goto_url_action(task_start))
                    time.sleep(0.5)
                    current_url = info["page"].url
                except Exception:
                    pass

        urls_visited.add(current_url)
        url_history.append(current_url)

        verifier = Verifier() if mode in (
            "verifier_llm_phase3b", "verifier_gate_llm_phase3b"
        ) else None
        scorer = RiskScorer() if mode == "verifier_gate_llm_phase3b" else None

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
                desc = "SCROLL (no interactable)"
                risk_level = "LOW"
                latency = 0.0
                action_type_str = "SCROLL"
                typed_text = None
                plan_text = ""
            else:
                max_retries = 5
                action = None
                desc = ""
                risk_level = ""
                latency = 0.0
                skip_ids = set()
                action_type_str = ""
                typed_text = None
                plan_text = ""

                for attempt in range(max_retries):
                    res.actions_proposed += 1

                    avail_click = [e for e in clickable
                                   if e["id"] not in skip_ids]
                    avail_type = [e for e in typeable
                                  if e["id"] not in skip_ids]
                    if not avail_click and not avail_type:
                        avail_click = clickable
                        avail_type = typeable

                    llm_result = choose_action_phase3b(
                        instruction, current_url,
                        avail_click, avail_type,
                        action_history,
                    )
                    latency = llm_result["latency"]
                    latencies.append(latency)

                    elem_id = llm_result["id"]
                    elem_name = llm_result.get("name", "")
                    elem_role = llm_result.get("role", "")
                    action_type_str = llm_result["type"]
                    typed_text = llm_result.get("text")
                    plan_text = llm_result.get("plan", "")
                    alignment = llm_result.get("goal_alignment", 0.0)

                    # Track plan
                    if plan_text:
                        res.plan_present_count += 1
                        plan_lengths.append(len(plan_text))
                    alignment_scores.append(alignment)

                    if not elem_id:
                        action = create_scroll_action("down")
                        desc = "SCROLL (no element)"
                        risk_level = "LOW"
                        action_type_str = "SCROLL"
                        break

                    # Build action
                    if action_type_str == "TYPE" and typed_text:
                        action = create_type_action(
                            text=typed_text, element_id=elem_id)
                        desc = (f"TYPE [{elem_id}] '{elem_name}' "
                                f"← \"{typed_text[:30]}\"")
                    else:
                        action = create_click_action(element_id=elem_id)
                        desc = (f"CLICK [{elem_id}] {elem_role} "
                                f"'{elem_name}'")
                        action_type_str = "CLICK"
                        typed_text = None

                    is_submission = (action_type_str == "CLICK"
                                    and is_submission_click(elem_name))
                    if is_submission:
                        res.submission_attempts += 1

                    # Score risk (all modes)
                    tmp_scorer = RiskScorer()
                    risk_level = tmp_scorer.score(
                        action, elem_name, current_url)
                    if risk_level == "HIGH":
                        res.high_risk_count += 1
                    elif risk_level == "MEDIUM":
                        res.medium_risk_count += 1
                    else:
                        res.low_risk_count += 1

                    # Baseline: no gate
                    if mode == "baseline_llm_phase3b":
                        if risk_level == "HIGH":
                            res.high_risk_executed += 1
                        if is_submission:
                            res.submission_executed += 1
                        risk_level = "N/A"
                        break

                    # Verifier
                    v_result = verifier.validate(
                        action, elements, current_url)
                    if not v_result.valid:
                        res.actions_blocked_verifier += 1
                        skip_ids.add(elem_id)
                        if verbose:
                            print(f"      ⛔ V: {v_result.reason[:55]}")
                        if attempt == max_retries - 1:
                            action = create_scroll_action("down")
                            desc = "SCROLL (verifier exhausted)"
                            risk_level = "LOW"
                            action_type_str = "SCROLL"
                        continue

                    # Gate
                    if mode == "verifier_gate_llm_phase3b" and scorer:
                        risk_level = scorer.score(
                            action, elem_name, current_url)
                        allowed, gate_reason = scorer.gate(risk_level)
                        if not allowed:
                            res.actions_blocked_gate += 1
                            if risk_level == "HIGH":
                                res.high_risk_blocked += 1
                            if is_submission:
                                res.submission_blocked += 1
                            skip_ids.add(elem_id)
                            if verbose:
                                print(f"      🚫 G: {gate_reason[:55]}")
                            if attempt == max_retries - 1:
                                action = create_scroll_action("down")
                                desc = "SCROLL (gate exhausted)"
                                risk_level = "LOW"
                                action_type_str = "SCROLL"
                            continue
                        else:
                            if risk_level == "HIGH":
                                res.high_risk_executed += 1
                            if is_submission:
                                res.submission_executed += 1
                    elif mode == "verifier_llm_phase3b":
                        if risk_level == "HIGH":
                            res.high_risk_executed += 1
                        if is_submission:
                            res.submission_executed += 1

                    break

            # Record
            if verifier and action:
                verifier.record_action(action, current_url, elements)

            if action_type_str == "TYPE":
                res.type_count += 1
                if typed_text:
                    text_lengths.append(len(typed_text))
            elif action_type_str == "CLICK":
                res.click_count += 1

            res.actions_executed += 1
            action_history.append(desc)

            if verbose:
                a_tag = "TYPE" if action_type_str == "TYPE" else "CLK "
                plan_preview = f" P=\"{plan_text[:25]}\"" if plan_text else ""
                print(f"    Step {step+1:>2}/{MAX_STEPS} │ "
                      f"[{domain:>6}] "
                      f"URL={current_url[:35]:<35} │ "
                      f"{a_tag} {desc[:35]:<35} │ "
                      f"Risk={risk_level:<6} "
                      f"Lat={latency:.1f}s{plan_preview}")

            # Execute
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
                verifier.detect_state_change(
                    prev_url, new_url, action, elements)

            res.steps_taken = step + 1
            if done:
                break

        # Post-episode
        for i in range(1, len(url_history)):
            if url_history[i] == url_history[i - 1]:
                res.loop_count += 1
        res.unique_urls = len(urls_visited)
        res.avg_llm_latency = sum(latencies) / max(len(latencies), 1)
        if res.steps_taken == 0:
            res.steps_taken = MAX_STEPS

        if len(url_history) > 1:
            changes = sum(1 for i in range(1, len(url_history))
                          if url_history[i] != url_history[i - 1])
            res.new_page_rate = round(
                changes / max(res.steps_taken, 1), 3)
        if url_history:
            streak = max_s = 1
            for i in range(1, len(url_history)):
                if url_history[i] == url_history[i - 1]:
                    streak += 1
                    max_s = max(max_s, streak)
                else:
                    streak = 1
            res.max_same_url_streak = max_s

        if text_lengths:
            res.avg_text_length = round(
                sum(text_lengths) / len(text_lengths), 1)
            res.max_text_length = max(text_lengths)

        res.chaos_score = round(
            (res.high_risk_executed + res.submission_attempts)
            / max(res.steps_taken, 1), 3)

        # typed_when_expected
        if res.instruction_contains_type_keyword and res.type_count > 0:
            res.typed_when_expected = True

        # goal alignment average
        if alignment_scores:
            res.goal_alignment_score = round(
                sum(alignment_scores) / len(alignment_scores), 3)

        # avg plan length
        if plan_lengths:
            res.avg_plan_length = round(
                sum(plan_lengths) / len(plan_lengths), 1)

    except Exception as e:
        res.error = str(e)[:80]

    return res


# ═══════════════════════════════════════════════════════════════
#  Validation
# ═══════════════════════════════════════════════════════════════
def run_validation(forum_tasks, gitlab_tasks):
    print("\n" + "=" * 74)
    print("  PHASE 3B VALIDATION — 1 forum + 1 gitlab, baseline")
    print("=" * 74)

    global MAX_STEPS
    orig = MAX_STEPS
    MAX_STEPS = 5

    for label, tasks, start_url in [
        ("FORUM", forum_tasks, FORUM_URL),
        ("GITLAB", gitlab_tasks, GITLAB_URL),
    ]:
        task = tasks[0]
        print(f"\n  [{label}] Task ID={task['task_id']}: "
              f"{task['intent'][:60]}")

        config_path = os.path.join(
            PROJECT_ROOT, f"_temp_val_p3b_{label.lower()}.json")
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
                env, task, "baseline_llm_phase3b",
                config_path, verbose=True)
            print(f"\n  Result: steps={result.steps_taken} "
                  f"rew={result.reward_total:.1f} "
                  f"C={result.click_count} T={result.type_count} "
                  f"plans={result.plan_present_count} "
                  f"align={result.goal_alignment_score:.3f} "
                  f"lat={result.avg_llm_latency:.2f}s "
                  f"err={'None' if not result.error else result.error}")
            if result.error:
                print(f"  ❌ {label} FAILED: {result.error}")
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
    print("\n  ✅ Both domains validated — proceeding")
    return True


# ═══════════════════════════════════════════════════════════════
#  Full Experiment
# ═══════════════════════════════════════════════════════════════
def run_experiment():
    total_start = time.time()
    total_tasks = NUM_FORUM_TASKS + NUM_GITLAB_TASKS

    print("=" * 80)
    print("  PHASE 3B — INSTRUCTION-CONDITIONED AUTONOMY (qwen3:8b)")
    print("=" * 80)
    print(f"  Modes:        {', '.join(MODES)}")
    print(f"  Forum tasks:  {NUM_FORUM_TASKS}")
    print(f"  GitLab tasks: {NUM_GITLAB_TASKS}")
    print(f"  Total/mode:   {total_tasks}")
    print(f"  Steps/task:   {MAX_STEPS}")
    print(f"  Model:        qwen3:8b (temp=0.7)")
    print(f"  Planning:     YES (PLAN + ACTION scaffold)")
    print(f"  TYPE promo:   YES (instruction keywords)")
    print(f"  Output:       {RESULTS_FILE}")
    print("=" * 80)

    forum_tasks = load_forum_tasks(NUM_FORUM_TASKS)
    gitlab_tasks = load_gitlab_tasks(NUM_GITLAB_TASKS)
    all_tasks = forum_tasks + gitlab_tasks

    f_ids = len(set(t["task_id"] for t in forum_tasks))
    g_ids = len(set(t["task_id"] for t in gitlab_tasks))
    print(f"\n📋 Forum: {len(forum_tasks)} ({f_ids} unique)")
    print(f"📋 GitLab: {len(gitlab_tasks)} ({g_ids} unique)")

    # Count instruction keyword tasks
    type_kw_count = sum(1 for t in all_tasks
                        if should_promote_type(t["intent"]))
    print(f"📋 Tasks with TYPE-keywords: {type_kw_count}/{total_tasks}")

    ok = run_validation(forum_tasks, gitlab_tasks)
    if not ok:
        print("Aborting.")
        return

    forum_config = os.path.join(PROJECT_ROOT, "_temp_p3b_forum.json")
    gitlab_config = os.path.join(PROJECT_ROOT, "_temp_p3b_gitlab.json")
    with open(forum_config, "w") as f:
        json.dump({"start_url": FORUM_URL}, f)
    with open(gitlab_config, "w") as f:
        json.dump({"start_url": GITLAB_URL}, f)

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
                config_path = (gitlab_config if domain == "gitlab"
                               else forum_config)
                tag = "GL" if domain == "gitlab" else "FM"
                label = (f"[{mode}] {tag} {i+1:>2}/{total_tasks} "
                         f"(id={task['task_id']:<4})")
                print(f"  {label} ...", end=" ", flush=True)

                result = run_single_task(env, task, mode, config_path)
                all_results.append(result)

                elapsed = time.time() - t0
                flag = ("✅" if not result.error
                        else f"⚠️  {result.error[:20]}")
                print(
                    f"{flag} {elapsed:5.1f}s │ "
                    f"s={result.steps_taken:>2} "
                    f"r={result.reward_total:>5.1f} "
                    f"u={result.unique_urls:>2} "
                    f"V={result.actions_blocked_verifier:>2} "
                    f"G={result.actions_blocked_gate:>2} "
                    f"H={result.high_risk_count:>2} "
                    f"C={result.click_count:>2} "
                    f"T={result.type_count:>2} "
                    f"sub={result.submission_attempts:>1} "
                    f"plan={result.plan_present_count:>2} "
                    f"align={result.goal_alignment_score:.2f} "
                    f"lat={result.avg_llm_latency:.1f}s"
                )
        finally:
            try:
                env.close()
            except Exception:
                pass

        elapsed = time.time() - mode_start
        print(f"\n  ⏱  Mode '{mode}' in {elapsed:.1f}s")

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
            "avg_text_length", "max_text_length",
            "submission_attempts", "submission_executed",
            "submission_blocked",
            "high_risk_executed", "high_risk_blocked",
            "chaos_score",
            "instruction_contains_type_keyword", "typed_when_expected",
            "plan_present", "goal_alignment_score", "avg_plan_length",
        ])
        for r in all_results:
            writer.writerow([
                r.mode, r.domain, r.task_id,
                r.steps_taken, r.reward_total, r.unique_urls,
                r.actions_blocked_verifier, r.actions_blocked_gate,
                r.actions_proposed, r.actions_executed, r.loop_count,
                r.high_risk_count, r.medium_risk_count, r.low_risk_count,
                f"{r.avg_llm_latency:.3f}",
                f"{r.new_page_rate:.3f}", r.max_same_url_streak,
                r.click_count, r.type_count,
                f"{r.avg_text_length:.1f}", r.max_text_length,
                r.submission_attempts, r.submission_executed,
                r.submission_blocked,
                r.high_risk_executed, r.high_risk_blocked,
                f"{r.chaos_score:.3f}",
                int(r.instruction_contains_type_keyword),
                int(r.typed_when_expected),
                r.plan_present_count,
                f"{r.goal_alignment_score:.3f}",
                f"{r.avg_plan_length:.1f}",
            ])

    print(f"\n📄 Results saved to {RESULTS_FILE}")

    # ═══════════════════════════════════════════════════════════
    #  Aggregate Summary
    # ═══════════════════════════════════════════════════════════
    total_elapsed = time.time() - total_start

    print(f"\n{'═' * 145}")
    print(f"  AGGREGATE SUMMARY — Phase 3B by Mode × Domain")
    print(f"{'═' * 145}")

    header = (
        f"  {'Mode':<30} {'Dom':<6} {'N':>3} "
        f"{'Steps':>5} {'Rew':>5} {'URLs':>4} "
        f"{'H':>4} {'M':>4} {'L':>4} "
        f"{'VBlk':>4} {'GBlk':>4} "
        f"{'CLK':>4} {'TYP':>4} "
        f"{'Sub':>3} {'HExe':>4} {'HBlk':>4} "
        f"{'Plan':>4} {'Align':>5} {'Lat':>6}"
    )
    print(header)
    print("  " + "─" * 135)

    for m in MODES:
        for dom in ["forum", "gitlab"]:
            mrs = [r for r in all_results
                   if r.mode == m and r.domain == dom]
            if not mrs:
                continue
            n = len(mrs)
            print(
                f"  {m:<30} {dom:<6} {n:>3} "
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
                f"{sum(r.high_risk_executed for r in mrs):>4} "
                f"{sum(r.high_risk_blocked for r in mrs):>4} "
                f"{sum(r.plan_present_count for r in mrs):>4} "
                f"{sum(r.goal_alignment_score for r in mrs)/n:>5.3f} "
                f"{sum(r.avg_llm_latency for r in mrs)/n:>5.2f}s"
            )

    print("  " + "─" * 135)
    for m in MODES:
        mrs = [r for r in all_results if r.mode == m]
        if not mrs:
            continue
        n = len(mrs)
        print(
            f"  {m:<30} {'ALL':<6} {n:>3} "
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
            f"{sum(r.high_risk_executed for r in mrs):>4} "
            f"{sum(r.high_risk_blocked for r in mrs):>4} "
            f"{sum(r.plan_present_count for r in mrs):>4} "
            f"{sum(r.goal_alignment_score for r in mrs)/n:>5.3f} "
            f"{sum(r.avg_llm_latency for r in mrs)/n:>5.2f}s"
        )

    print(f"\n  ⏱  Total: {total_elapsed:.1f}s ({total_elapsed/60:.1f} min)")

    for p in [forum_config, gitlab_config]:
        if os.path.exists(p):
            os.remove(p)

    # ═══════════════════════════════════════════════════════════
    #  Final Banner
    # ═══════════════════════════════════════════════════════════
    print()
    print("══════════════════════════════════════════")
    print("PHASE 3B — GOAL-DIRECTED AUTONOMY COMPLETE")
    print("══════════════════════════════════════════")
    print("Instruction-conditioned agent active")
    print("Planning scaffold enabled")
    print("Goal alignment metrics computed")
    print("Chaos vs gated comparison complete")
    print(f"{len(all_results)} runs completed")
    print("Outputs:")
    print(f"  {RESULTS_FILE}")
    print("  reports_llm_phase3b/")
    print("══════════════════════════════════════════")
    print()
    print("PHASE 3B LOCKED.")
    print("READY FOR PHASE 4.")


if __name__ == "__main__":
    run_experiment()
