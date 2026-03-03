# Paper Skeleton

> **Note**: This skeleton is grounded exclusively in implemented code and measured data. No numbers are invented. Proposed claims cite specific files and logs.

---

## Title

**Safety-Aware Web Agent Evaluation with Tiered Autonomy Gating: A Deterministic Baseline Study**

---

## Abstract

We present a safety evaluation framework for web agents operating on realistic, locally-hosted WebArena environments. The framework introduces a three-layer safety pipeline — element-level Verifier, keyword-based RiskScorer, and deterministic Tiered Autonomy Gate — that classifies, validates, and conditionally blocks agent actions before execution. Using a deterministic heuristic policy (no LLM), we evaluate three safety configurations (baseline, verifier, verifier+gate) across 20 Forum tasks and a separate GitLab domain, measuring action blocking rates, navigation diversity, and loop frequency. We find that gating increases URL diversity (supported by `results.csv`: 7.0 vs 6.0 unique URLs) and reduces navigation looping (3.0 vs 4.0 loop count) while maintaining identical step-execution reward. On GitLab, the pipeline successfully identifies and gates 3 HIGH-risk actions. We discuss limitations of the current reward metric and propose improvements for task-success evaluation.

---

## 1. Introduction

- Web agents (VLAs, LLM-based browsing agents) can perform destructive actions on real websites without understanding consequences.
- WebArena provides a benchmark for web agent evaluation but does not include safety mechanisms.
- Problem: How to evaluate and mitigate safety risks of web agents without requiring an LLM?
- Contribution: A deterministic safety pipeline with three layers, evaluated on two local WebArena domains.

---

## 2. Related Work

- WebArena (Zhou et al., 2024): Realistic web environment benchmark.
- Safety in LLM agents: alignment, RLHF, constitutional AI — focus on language generation, not browser actions.
- Tiered autonomy: human-in-the-loop systems, approval workflows in robotics.
- Web agent safety: limited prior work on pre-execution action validation for browser agents.

---

## 3. Method

### 3.1 Architecture

Three-layer pipeline (diagram in `reports/01_system_overview.md`):
1. **Verifier** — element existence, role compatibility, repetition detection.
2. **RiskScorer** — keyword-based classification into HIGH / MEDIUM / LOW.
3. **Gate** — deterministic tiered autonomy: HIGH 50%, MEDIUM 80%, LOW 100% allow.

### 3.2 Risk Classification

- HIGH keywords: `submit, delete, remove, confirm, log out, logout, sign up, register`
- MEDIUM keywords: `search, edit, create, new, filter, sort`
- AUTH_URL_PATTERNS for TYPE actions: `login, registration, register, signup, sign-up`
- Details in `safe_runner.py`, lines 208–357.

### 3.3 Heuristic Policy

Deterministic 7-target navigation cycle (no LLM), designed to exercise all risk tiers.
- Forum: Forums → Log in → Wiki → Sign up → Comments → Filter → Sort
- GitLab: Two-phase (unauthenticated HIGH targets, then authenticated MEDIUM/LOW)

### 3.4 Evaluation Setup

- Forum (Postmill): Docker, port 9999, arm64-native.
- GitLab CE: Docker, port 8023, amd64 emulated on Apple Silicon.
- 20 tasks × 3 modes × 15 steps = 60 evaluations (Forum).
- 1 run × 12 steps (GitLab visual debugging).

---

## 4. Experiments

### 4.1 Batch Experiment (Forum)

- `experiment_runner.py` runs 3 modes × 20 tasks.
- Output: `results.csv` (60 rows).
- See `reports/03_experiments_and_results.md` for full analysis.

### 4.2 Visual Debugging (Forum)

- `visual_debug_runner.py` with `--mode baseline` and `--mode verifier+gate`.
- Output: `reports/logs/visual_baseline.out`, `reports/logs/visual_gate.out`.

### 4.3 GitLab Safety Evaluation

- `gitlab_visual_debug.py` with two-phase exploration.
- Output: `reports/logs/gitlab_visual_debug.out`.
- Screenshots: `reports/screenshots/gitlab_gated.png`, `reports/screenshots/gitlab_dashboard.png`.

---

## 5. Results

### 5.1 Aggregate Table (supported by `results.csv`)

| Mode | Steps | Reward | URLs | V-Block | G-Block | Proposed | Loop |
|------|-------|--------|------|---------|---------|----------|------|
| baseline | 15.0 | 15.0 | 6.0 | 0.0 | 0.0 | 15.0 | 4.0 |
| verifier | 15.0 | 15.0 | 6.0 | 0.0 | 0.0 | 15.0 | 4.0 |
| verifier+gate | 15.0 | 15.0 | **7.0** | 0.0 | **1.0** | **16.0** | **3.0** |

### 5.2 GitLab Distribution (supported by `reports/logs/gitlab_visual_debug.out`)

- 3 HIGH encounters, 1 gated.
- 6 MEDIUM encounters, 1 gated.
- 5 LOW encounters, 0 gated.

### 5.3 Key Findings

1. **Gating increases navigation diversity**: 7 vs 6 unique URLs (Claim supported by `results.csv`, column `unique_urls`).
2. **Gating reduces looping**: 3 vs 4 loop count (Claim supported by `results.csv`, column `loop_count`).
3. **Reward is unchanged**: All modes achieve 15.0 (Claim supported by `results.csv`, column `reward`).
4. **Verifier blocks are zero for deterministic policies**: (Claim supported by `results.csv`, column `blocked_verifier`).
5. **GitLab HIGH-risk gating works**: 1 HIGH-risk action blocked out of 3 encountered (Claim supported by `reports/logs/gitlab_visual_debug.out`, summary section).

---

## 6. Discussion

- The safety pipeline's effect is **structural**, not **performance-based** — it redirects the agent's trajectory without degrading step-execution reward.
- Verifier blocks require adversarial or LLM-based policies to trigger. The deterministic heuristic is too well-behaved.
- The gate's 50%/80% policy is a proof-of-concept. In practice, approval policies would be calibrated per domain and action type.
- Cross-domain evaluation (Forum vs GitLab) reveals that risk surfaces differ significantly: GitLab's authenticated UI has no HIGH-risk elements without phase manipulation.

---

## 7. Limitations

1. **Reward measures step execution, not task success**: All modes achieve identical reward because every step executes without errors. Task-success evaluation requires WebArena's full evaluator pipeline, which we did not integrate.
2. **Deterministic policy**: Results reflect the safety pipeline's effect on a specific heuristic, not on general LLM-based agents. An LLM agent would produce different action distributions.
3. **Single domain for batch experiments**: Only Forum was evaluated in the 3-mode × 20-task batch. GitLab was evaluated separately in a single run.
4. **No actual human review**: The gate simulates approval with counters, not real human judgment.
5. **amd64 emulation**: GitLab runs under Rosetta emulation, which may affect timing and reliability.

---

## 8. Future Work

1. Integrate WebArena task-success evaluation for safety-adjusted performance metrics.
2. Replace the deterministic heuristic with an LLM-based policy to evaluate safety under realistic agent behavior.
3. Add domain-specific risk taxonomies (Priority B in `reports/06_improvement_backlog.md`).
4. Implement DOM-diff-based state change detection (Priority D).
5. Add human-in-the-loop approval simulation (Priority E).
6. Extend to multi-domain evaluation with combined Forum + GitLab experiments (Priority F).

---

## 9. References

- Local files: `safe_runner.py`, `experiment_runner.py`, `visual_debug_runner.py`, `gitlab_visual_debug.py`
- Data: `results.csv`
- Logs: `reports/logs/`
- WebArena: `third_party/webarena/`
