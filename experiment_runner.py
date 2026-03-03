"""
Experiment harness for comparative evaluation of safety layers.

Runs three modes side-by-side:
    A) baseline        — raw heuristic policy, no safety layers
    B) verifier        — heuristic + Verifier (element / repetition checks)
    C) verifier+gate   — heuristic + Verifier + RiskScorer tiered gate

Each mode runs NUM_TASKS forum tasks for MAX_STEPS steps (headless).
Results → results.csv  +  printed summary table.

Usage:
    python experiment_runner.py
"""

import csv
import json
import os
import sys
import time
import traceback
from dataclasses import dataclass

# ── Import safe_runner (this sets env vars + sys.path) ──
import safe_runner
from safe_runner import (
    Verifier,
    VerifyResult,
    RiskScorer,
    choose_action,
    parse_a11y_tree,
    find_clickable_elements,
    FORUM_URL,
    PROJECT_ROOT,
    CONFIG_FILE,
    MAX_STEPS,
)

# Now browser_env is importable (safe_runner added it to sys.path)
from browser_env import ScriptBrowserEnv
from browser_env.actions import (
    create_none_action,
    create_scroll_action,
)

# ═══════════════════════════════════════════════════════════════
#  Experiment Config
# ═══════════════════════════════════════════════════════════════
NUM_TASKS = 20
MODES = ["baseline", "verifier", "verifier+gate"]
RESULTS_FILE = os.path.join(PROJECT_ROOT, "results.csv")


# ═══════════════════════════════════════════════════════════════
#  Per-Task Result
# ═══════════════════════════════════════════════════════════════
@dataclass
class TaskResult:
    mode: str
    task_id: int
    steps_taken: int = 0
    reward_total: float = 0.0
    unique_urls: int = 0
    actions_proposed: int = 0
    actions_executed: int = 0
    actions_blocked_verifier: int = 0
    actions_blocked_gate: int = 0
    loop_count: int = 0      # consecutive repeated-URL count
    error: str = ""


# ═══════════════════════════════════════════════════════════════
#  Task Loader
# ═══════════════════════════════════════════════════════════════
def load_forum_tasks(n: int = NUM_TASKS):
    """Load up to *n* distinct forum/reddit tasks from test.raw.json.

    If fewer than n reddit tasks exist, the list cycles over to fill.
    Each task is patched to use FORUM_URL with no login requirement.
    """
    with open(CONFIG_FILE) as f:
        all_tasks = json.load(f)

    reddit_tasks = [t for t in all_tasks if "reddit" in t.get("sites", [])]
    if not reddit_tasks:
        raise RuntimeError("No reddit/forum tasks found in config")

    tasks = []
    for i in range(n):
        task = dict(reddit_tasks[i % len(reddit_tasks)])  # shallow copy
        task["start_url"] = FORUM_URL
        task["storage_state"] = None
        task["require_login"] = False
        tasks.append(task)

    return tasks


# ═══════════════════════════════════════════════════════════════
#  Single-Task Runner
# ═══════════════════════════════════════════════════════════════
def run_single_task(env, task, mode, config_path):
    """Run one task under the specified mode. Returns TaskResult."""
    instruction = task["intent"]
    res = TaskResult(mode=mode, task_id=task["task_id"])

    urls_visited = set()
    url_history = []

    try:
        # ── Reset browser ──
        obs, info = env.reset(options={"config_file": config_path})
        current_url = info["page"].url
        urls_visited.add(current_url)
        url_history.append(current_url)

        # ── Instantiate layers per-task (fresh state) ──
        verifier = Verifier() if mode in ("verifier", "verifier+gate") else None
        scorer   = RiskScorer() if mode == "verifier+gate" else None

        if verifier:
            verifier.prev_url = current_url

        done = False
        for step in range(MAX_STEPS):
            tree_text = obs.get("text", "")
            elements = parse_a11y_tree(tree_text)
            current_url = info["page"].url

            # ── Choose + validate action ──
            skip_names = set()
            max_retries = 8
            action = None

            for attempt in range(max_retries):
                res.actions_proposed += 1

                try:
                    action, _ = choose_action(
                        instruction, elements, step, skip_names
                    )
                except Exception:
                    action = create_none_action()
                    break

                elem_id = action.get("element_id", "")
                elem = (Verifier._find_elem_by_id(elements, elem_id)
                        if elem_id else None)
                elem_text = elem["name"] if elem else ""

                # ── MODE A: baseline — skip all checks ──
                if mode == "baseline":
                    break

                # ── MODE B & C: Verifier ──
                v_result = verifier.validate(action, elements, current_url)
                if not v_result.valid:
                    res.actions_blocked_verifier += 1
                    if elem_id and elem:
                        skip_names.add(elem["name"])
                    if attempt == max_retries - 1:
                        action = create_scroll_action("down")
                    continue

                # ── MODE C: Risk gate ──
                if mode == "verifier+gate" and scorer:
                    risk = scorer.score(action, elem_text, current_url)
                    allowed, _ = scorer.gate(risk)
                    if not allowed:
                        res.actions_blocked_gate += 1
                        if elem_id and elem:
                            skip_names.add(elem["name"])
                        if attempt == max_retries - 1:
                            action = create_scroll_action("down")
                        continue

                break  # action accepted

            # ── Record in verifier ──
            if verifier:
                verifier.record_action(action, current_url, elements)

            res.actions_executed += 1

            # ── Execute ──
            prev_url = current_url
            try:
                obs, reward, terminated, truncated, info = env.step(action)
                done = terminated or truncated
                res.reward_total += reward
            except Exception as e:
                # Attempt recovery
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

            # State change detection
            if verifier:
                verifier.detect_state_change(prev_url, new_url, action, elements)

            res.steps_taken = step + 1

            if done:
                break

        # ── Loop frequency: count consecutive same-URL pairs ──
        for i in range(1, len(url_history)):
            if url_history[i] == url_history[i - 1]:
                res.loop_count += 1

        res.unique_urls = len(urls_visited)
        if res.steps_taken == 0:
            res.steps_taken = MAX_STEPS

    except Exception as e:
        res.error = str(e)[:80]

    return res


# ═══════════════════════════════════════════════════════════════
#  Experiment Runner
# ═══════════════════════════════════════════════════════════════
def run_experiment():
    print("=" * 74)
    print("  EXPERIMENT HARNESS — Comparative Safety Layer Evaluation")
    print("=" * 74)
    print(f"  Modes:       {', '.join(MODES)}")
    print(f"  Tasks/mode:  {NUM_TASKS}")
    print(f"  Steps/task:  {MAX_STEPS}")
    print(f"  Headless:    True")
    print(f"  Output:      {RESULTS_FILE}")
    print("=" * 74)

    tasks = load_forum_tasks(NUM_TASKS)
    unique_ids = len(set(t["task_id"] for t in tasks))
    print(f"\n📋 Loaded {len(tasks)} tasks ({unique_ids} unique IDs)")

    # ── Write temp config (same start_url for all tasks) ──
    config_path = os.path.join(PROJECT_ROOT, "_temp_experiment_config.json")
    with open(config_path, "w") as f:
        json.dump({"start_url": FORUM_URL}, f)

    all_results = []

    for mode in MODES:
        print(f"\n{'━' * 74}")
        print(f"  MODE: {mode.upper()}")
        print(f"{'━' * 74}")

        # One browser env per mode — reuse across tasks via reset()
        env = ScriptBrowserEnv(
            headless=True,
            observation_type="accessibility_tree",
            current_viewport_only=True,
            viewport_size={"width": 1280, "height": 720},
            sleep_after_execution=0.3,
        )

        mode_start = time.time()

        try:
            for i, task in enumerate(tasks):
                t0 = time.time()
                label = f"[{mode}] Task {i+1:>2}/{NUM_TASKS} (id={task['task_id']:<4})"
                print(f"  {label} ...", end=" ", flush=True)

                result = run_single_task(env, task, mode, config_path)
                all_results.append(result)

                elapsed = time.time() - t0
                flag = "✅" if not result.error else f"⚠️  {result.error[:35]}"
                print(
                    f"{flag} {elapsed:5.1f}s │ "
                    f"steps={result.steps_taken:>2} "
                    f"rew={result.reward_total:>5.1f} "
                    f"urls={result.unique_urls:>2} "
                    f"blk_v={result.actions_blocked_verifier:>2} "
                    f"blk_g={result.actions_blocked_gate:>2} "
                    f"loops={result.loop_count:>2}"
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
            "mode", "task_id", "steps", "reward", "unique_urls",
            "blocked_verifier", "blocked_gate",
            "actions_proposed", "actions_executed", "loop_count",
        ])
        for r in all_results:
            writer.writerow([
                r.mode, r.task_id, r.steps_taken, r.reward_total,
                r.unique_urls, r.actions_blocked_verifier,
                r.actions_blocked_gate, r.actions_proposed,
                r.actions_executed, r.loop_count,
            ])

    print(f"\n📄 Results saved to {RESULTS_FILE}")

    # ═══════════════════════════════════════════════════════════
    #  Aggregate Summary Table
    # ═══════════════════════════════════════════════════════════
    print(f"\n{'═' * 80}")
    print(f"  AGGREGATE SUMMARY ({NUM_TASKS} tasks per mode)")
    print(f"{'═' * 80}")

    col_w = 16  # column width for each mode
    header = f"  {'Metric':<30}"
    for m in MODES:
        header += f" {m:>{col_w}}"
    print(header)
    print("  " + "─" * (30 + (col_w + 1) * len(MODES)))

    # Define metrics as (label, aggregation_fn)
    metrics = [
        ("avg_steps",
         lambda rs: sum(r.steps_taken for r in rs) / max(len(rs), 1)),
        ("avg_reward",
         lambda rs: sum(r.reward_total for r in rs) / max(len(rs), 1)),
        ("avg_unique_urls",
         lambda rs: sum(r.unique_urls for r in rs) / max(len(rs), 1)),
        ("total_actions_proposed",
         lambda rs: sum(r.actions_proposed for r in rs)),
        ("total_actions_executed",
         lambda rs: sum(r.actions_executed for r in rs)),
        ("total_blocked_verifier",
         lambda rs: sum(r.actions_blocked_verifier for r in rs)),
        ("total_blocked_gate",
         lambda rs: sum(r.actions_blocked_gate for r in rs)),
        ("loop_frequency",
         lambda rs: sum(r.loop_count for r in rs)),
        ("tasks_with_errors",
         lambda rs: sum(1 for r in rs if r.error)),
    ]

    for name, fn in metrics:
        row = f"  {name:<30}"
        for m in MODES:
            mode_rs = [r for r in all_results if r.mode == m]
            val = fn(mode_rs)
            if isinstance(val, float):
                row += f" {val:>{col_w}.2f}"
            else:
                row += f" {val:>{col_w}}"
        print(row)

    print(f"  {'═' * (30 + (col_w + 1) * len(MODES))}")

    # ═══════════════════════════════════════════════════════════
    #  Print first 5 rows of CSV
    # ═══════════════════════════════════════════════════════════
    print(f"\n📊 First 5 rows of results.csv:")
    fmt = "  {:<16} {:>8} {:>6} {:>7} {:>5} {:>7} {:>7}"
    print(fmt.format("mode", "task_id", "steps", "reward", "urls", "blk_v", "blk_g"))
    print("  " + "─" * 58)
    for r in all_results[:5]:
        print(fmt.format(
            r.mode, r.task_id, r.steps_taken,
            f"{r.reward_total:.1f}", r.unique_urls,
            r.actions_blocked_verifier, r.actions_blocked_gate
        ))

    # ── Cleanup ──
    if os.path.exists(config_path):
        os.remove(config_path)

    print(f"\n✅ Experiment complete.\n")


if __name__ == "__main__":
    run_experiment()
