# Phase 2 Summary

## Overview

Phase 2 expanded the LLM agent's action space from **click-only** to **click + structured TYPE** with a controlled SLOT allowlist. The experiment ran 135 tasks (3 modes × 45 tasks: 30 Forum + 15 GitLab) with `qwen3:8b` at temperature 0.7.

## Aggregate Results (mean ± std per task, totals for counts)

| Mode | Domain | N | Steps | Reward | URLs | HIGH | MED | LOW | V-Blk | G-Blk | CLK | TYP | Sub | GSub | Latency |
|------|--------|---|-------|--------|------|------|-----|-----|-------|-------|-----|-----|-----|------|---------|
| baseline_llm_phase2 | forum | 30 | 12.0±0.0 | 12.0±0.0 | 6.9±1.9 | 0.8±1.1 | 1.3±0.9 | 8.7±1.8 | 0 | 0 | 325 | 0 | 1 | 0 | 3.91±0.92 |
| baseline_llm_phase2 | gitlab | 15 | 12.0±0.0 | 12.0±0.0 | 7.2±1.7 | 0.1±0.3 | 1.1±1.1 | 10.4±1.7 | 0 | 0 | 173 | 0 | 20 | 0 | 6.68±0.63 |
| verifier_llm_phase2 | forum | 30 | 12.0±0.0 | 11.9±0.3 | 6.6±1.6 | 1.2±1.2 | 2.1±1.5 | 7.8±1.7 | 3 | 0 | 335 | 0 | 0 | 0 | 4.27±0.56 |
| verifier_llm_phase2 | gitlab | 15 | 12.0±0.0 | 12.0±0.0 | 6.8±1.9 | 0.0±0.0 | 1.7±1.8 | 9.9±2.0 | 4 | 0 | 174 | 0 | 19 | 0 | 7.04±1.29 |
| verifier_gate_llm_phase2 | forum | 30 | 12.0±0.0 | 12.0±0.2 | 6.7±1.6 | 0.8±1.1 | 1.8±1.4 | 8.4±1.9 | 0 | **10** | 323 | 0 | 2 | 0 | 4.33±0.83 |
| verifier_gate_llm_phase2 | gitlab | 15 | 12.0±0.0 | 12.0±0.0 | 7.3±2.1 | 0.0±0.0 | 1.2±1.2 | 10.7±1.2 | 4 | 0 | 178 | 0 | 16 | 0 | 6.56±1.23 |

### Mode-Level Totals

| Mode | N | HIGH | MED | LOW | V-Blk | G-Blk | CLK | TYP | Sub | GSub | Latency |
|------|---|------|-----|-----|-------|-------|-----|-----|-----|------|---------|
| baseline_llm_phase2 | 45 | 26 | 56 | 416 | 0 | 0 | 498 | **0** | 21 | 0 | 4.83±1.56 |
| verifier_llm_phase2 | 45 | 37 | 89 | 383 | **7** | 0 | 509 | **0** | 19 | 0 | 5.19±1.57 |
| verifier_gate_llm_phase2 | 45 | 25 | 73 | 413 | 4 | **10** | 501 | **0** | 18 | 0 | 5.07±1.43 |

## Key Findings

### 1. TYPE Actions Were Never Selected (TYP = 0 Everywhere)

The LLM chose **zero TYPE actions** across all 135 runs. This is the most important finding of Phase 2 and is explained in detail in `02_phase2_behavior_analysis.md`.

**Root cause**: The numbered action list presents all CLICK options first (indices 1–N), followed by TYPE options (indices N+1 through N+K*10, where K = number of typeable elements × 10 SLOTs). With typical pages having 50–100 clickable elements and 1–3 typeable elements, TYPE actions start at index 60+ while the LLM overwhelmingly picks low indices.

### 2. Phase 1 vs Phase 2 Comparison

| Metric | Phase 1 v2 (baseline) | Phase 2 (baseline) | Change |
|--------|----------------------|--------------------|--------|
| HIGH risk/task (forum) | 1.1±1.1 | 0.8±1.1 | −0.3 (stochastic noise) |
| MED risk/task (forum) | 2.0±1.6 | 1.3±0.9 | −0.7 |
| Latency (forum) | 2.54±0.80 | 3.91±0.92 | **+1.4s (+54%)** |
| Latency (gitlab) | 5.38±0.76 | 6.68±0.63 | **+1.3s (+24%)** |

The main impact of Phase 2: **latency increased** due to longer prompts (TYPE + SLOT options added ~30–100 extra lines to the prompt). Risk profile remained comparable to Phase 1.

### 3. Gate Still Active on HIGH Risk

The gate blocked **10 actions** in `verifier_gate_llm_phase2` forum tasks (0.3±0.5 per task). This confirms the gate policy is unchanged and operational.

### 4. Submission Tracking

- 21 submission attempts in baseline, 19 in verifier, 18 in gate
- **0 gated submissions** — submission buttons in the WebArena domains don't consistently match both `SUBMISSION_KEYWORDS` and `HIGH_KEYWORDS` simultaneously (e.g., "Create" is MEDIUM, not HIGH)
- GitLab has more submissions (1.1–1.3/task) than Forum (0.0–0.1/task)

## Baseline Confirmation

Baseline risk logging remains fixed: HIGH=26, MED=56, LOW=416 across 45 tasks — non-zero counts confirming Phase 1 v2 instrumentation is intact.
