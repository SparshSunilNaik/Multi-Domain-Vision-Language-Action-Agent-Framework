# Executive Summary

## What Was Built

A **stochastic LLM-based web agent** (Ollama `qwen3:8b`, temperature 0.7) that navigates real web applications (Forum and GitLab) inside the WebArena benchmark, wrapped with **inference-time safety layers** — a Verifier, a RiskScorer, and a Tiered Autonomy Gate — that classify, validate, and conditionally block browser actions before execution.

This replaces the earlier deterministic heuristic policy with a genuinely stochastic policy that makes different decisions on every run, enabling statistical analysis of safety layer behavior.

## Key Results (from `results_llm.csv`, N=15 tasks per mode)

| Mode | Domain | Steps | Reward | Unique URLs | HIGH | MED | LOW | V-Blk | G-Blk | Latency |
|------|--------|-------|--------|-------------|------|-----|-----|-------|-------|---------|
| baseline_llm | forum | 12.0 ± 0.0 | 12.0 ± 0.0 | 7.4 ± 1.6 | — | — | — | 0 | 0 | 2.50s |
| baseline_llm | gitlab | 12.0 ± 0.0 | 12.0 ± 0.0 | 8.4 ± 2.2 | — | — | — | 0 | 0 | 5.10s |
| verifier_llm | forum | 12.0 ± 0.0 | 11.9 ± 0.3 | 6.2 ± 2.1 | 9 | 10 | 82 | **1** | 0 | 2.76s |
| verifier_llm | gitlab | 12.0 ± 0.0 | 12.0 ± 0.0 | 6.8 ± 1.3 | 0 | 10 | 50 | 0 | 0 | 4.69s |
| verifier_gate_llm | forum | 12.0 ± 0.0 | 11.9 ± 0.3 | 7.2 ± 1.9 | 5 | 17 | 92 | **2** | **1** | 3.19s |
| verifier_gate_llm | gitlab | 12.0 ± 0.0 | 12.0 ± 0.0 | 6.4 ± 2.2 | 0 | 9 | 51 | 0 | 0 | 4.80s |

*Note: baseline_llm does not score risk levels (by design); "—" indicates no scoring was performed.*

## Claims We Can Safely Make

1. **The LLM policy is genuinely stochastic**: URL diversity ranges from 3–11 per task (σ=1.6–2.2), unlike the deterministic heuristic which always visited exactly 6.

2. **The LLM naturally triggers HIGH-risk actions**: 9 HIGH-risk actions on Forum across verifier_llm tasks (clicking "Sign up", "Log out", etc.) — the deterministic heuristic produced 0.

3. **The Verifier detects structurally invalid actions**: 1 block in verifier_llm, 2 blocks in verifier_gate_llm — both on Forum, where the LLM occasionally targets non-existent or repeated elements.

4. **The Gate blocks HIGH-risk actions**: 1 gate block observed (Task 67, Forum, H=3 encounters, G=1 blocked).

5. **Safety layers do not degrade step-execution reward**: Average reward is 11.9–12.0 across all modes (within noise).

6. **GitLab produces higher LLM latency**: 4.7–5.1s average vs 2.5–3.2s on Forum, due to larger accessibility trees.

## Claims We CANNOT Make

- **No task-completion measurement**: Reward = 1.0 per executed step, not task success. We cannot say whether the agent actually solved any task.
- **No statistical significance**: N=10 forum + 5 gitlab per mode is too small for confident p-values.
- **No generalization claim**: Results are specific to one LLM (qwen3:8b), one temperature (0.7), and two local WebArena domains.
- **No real-world safety claim**: The gate uses deterministic counters, not human judgment. This is a research prototype, not a deployable safety system.

## Files Produced

| File | Description |
|------|-------------|
| `llm_policy.py` | LLM policy module (Ollama qwen3:8b) |
| `experiment_runner_llm.py` | Multi-domain experiment runner (Forum + GitLab) |
| `results_llm.csv` | 45 rows of experimental data |
