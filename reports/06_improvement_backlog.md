# Improvement Backlog

Prioritized list of concrete next improvements, ordered by expected impact and feasibility.

---

## Priority A: Better Verifier Repetition Thresholds

**Current state**: `MAX_REPEAT = 2` with `HISTORY_SIZE = 10`. The deterministic heuristic cycles through 7 targets, so no (URL, element) pair exceeds the threshold.

**Improvement**:
- Make thresholds configurable per mode (stricter for safety-critical domains).
- Add **sliding window decay** — recent repeats weigh more than older ones.
- Add a **global** repetition counter (not just within the last 10 actions) to catch long-range loops.
- Add **DOM-diff-based** repetition detection: if the page content hasn't changed after 3 clicks, block further clicks regardless of element name.

**Expected impact**: Would trigger verifier blocks in batch mode even with the deterministic policy, producing a clearer separation between modes in experiments.

---

## Priority B: Better Risk Taxonomy (GitLab-Specific)

**Current state**: `RiskScorer` uses a single set of keywords designed for the Forum. GitLab-specific destructive actions are not covered:
- `AUTH_URL_PATTERNS` does not match GitLab's `/users/sign_in` (contains underscore, not in the pattern set).
- HIGH_KEYWORDS does not include `"merge"`, `"approve"`, `"close"`, `"archive"`, or `"transfer"`.
- No URL-based risk escalation for admin pages (`/admin/*`).

**Improvement**:
- Add domain-specific keyword profiles: `RiskScorer(domain="gitlab")` loads GitLab-specific keywords.
- Add URL-pattern-based risk escalation: any action on `/admin/*`, `/*/-/settings`, or `/*/-/edit` is automatically MEDIUM or HIGH.
- Add `"sign_in"` and `"sign_up"` (with underscores) to `AUTH_URL_PATTERNS`.

**Expected impact**: Would produce HIGH-risk encounters in the authenticated GitLab dashboard without needing the two-phase approach.

---

## Priority C: Task-Success Reward

**Current state**: Reward is 1.0 per successfully executed step. All modes achieve identical reward (15.0 for 15 steps). This metric cannot distinguish a useful agent from one that wanders aimlessly.

**Improvement**:
- Integrate WebArena's **evaluation harness** (`evaluators/`) to compute task-success scores based on the final page state.
- Add a `task_success` column to `results.csv`.
- Compute **safety-adjusted task success**: `success_rate × (1 - blocked_ratio)`.

**Expected impact**: Would reveal whether gating degrades task performance or just redirects behavior. This is the single most important metric for a publishable result.

---

## Priority D: State-Change Detectors (DOM / A11y Diff)

**Current state**: State change detection is limited to URL comparison. If the URL doesn't change, the Verifier only checks if the same element was clicked consecutively.

**Improvement**:
- Compute **a11y tree diff** between pre-step and post-step observations. If the tree is unchanged after a click, mark it as a no-op.
- Compute **DOM hash** or structural fingerprint. Track the last N DOM hashes and detect cycles.
- Use the diff to classify actions as **constructive** (new content appeared), **destructive** (content removed), or **neutral** (no change).

**Expected impact**: Would enable the Verifier to detect and block "stuck" agents that click UI elements without producing state changes, even if the element name changes each time.

---

## Priority E: Human-in-the-Loop UI / Approval Simulation

**Current state**: The gate uses deterministic counters (allow 50% HIGH, 80% MEDIUM). There is no actual human review.

**Improvement**:
- Add a **mock approval UI**: when a HIGH-risk action is proposed, pause execution and display the action, element, URL, and risk level in a terminal prompt. Accept `y/n` input.
- Add an **async approval queue**: HIGH-risk actions are queued and processed asynchronously, while LOW/MEDIUM actions proceed immediately.
- Log **approval latency** and **human override rate** as additional metrics.

**Expected impact**: Would demonstrate a realistic human-in-the-loop workflow for safety-critical web agent deployment. Essential for the "tiered autonomy" framing.

---

## Priority F: Multi-Domain Experiment Mode (Forum + GitLab)

**Current state**: `experiment_runner.py` only evaluates Forum tasks. `gitlab_visual_debug.py` is a separate, manual debugging tool. There is no combined evaluation.

**Improvement**:
- Extend `experiment_runner.py` to accept a `--domain` flag: `forum`, `gitlab`, or `both`.
- For GitLab tasks, use a subset of WebArena's GitLab task configurations (they exist in `test.raw.json` but are filtered out by `select_forum_task()`).
- Run the same 3-mode comparison on GitLab tasks.
- Produce a combined `results.csv` with a `domain` column.

**Expected impact**: Would produce cross-domain safety metrics, showing how the safety pipeline generalizes across different web applications with different risk surfaces.

---

## Implementation Timeline Estimate

| Priority | Effort | Dependencies |
|----------|--------|-------------|
| A — Repetition thresholds | 1–2 hours | None |
| B — Risk taxonomy | 2–3 hours | None |
| C — Task-success reward | 4–8 hours | WebArena evaluators |
| D — State-change detectors | 3–5 hours | None |
| E — Human-in-the-loop UI | 4–6 hours | Terminal UI library |
| F — Multi-domain mode | 3–5 hours | GitLab container + task selection |
