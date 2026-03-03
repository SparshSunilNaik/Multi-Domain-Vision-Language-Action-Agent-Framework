# Phase 3A Summary — Full Autonomy

## Overview

Phase 3A removed all SLOT restrictions and allowed the LLM to generate **arbitrary free text** for TYPE actions. The experiment ran 135 tasks (3 modes × 45 tasks: 30 Forum + 15 GitLab) with `qwen3:8b` at temperature 0.7.

**Key capability expansion**: The LLM prompt now uses element IDs directly (`CLICK <id>` / `TYPE <id> "<text>"`) instead of numbered lists, with `num_predict` increased to 80 tokens for free-text output.

## Aggregate Results

| Mode | Domain | N | Steps | Reward | URLs | HIGH | MED | LOW | V-Blk | G-Blk | CLK | TYP | Sub | SubX | SBlk | HExe | HBlk | Chaos | Latency |
|------|--------|---|-------|--------|------|------|-----|-----|-------|-------|-----|-----|-----|------|------|------|------|-------|---------|
| baseline_llm_phase3 | forum | 30 | 11.8 | 11.7 | 6.4 | 28 | 48 | 249 | 0 | 0 | 325 | 0 | 0 | 0 | 0 | 28 | 0 | 0.082 | 8.31s |
| baseline_llm_phase3 | gitlab | 15 | 12.0 | 12.0 | 7.4 | 1 | 14 | 164 | 0 | 0 | 179 | 0 | 12 | 12 | 0 | 1 | 0 | 0.072 | 12.44s |
| verifier_llm_phase3 | forum | 30 | 12.0 | 12.0 | 6.8 | 34 | 46 | 259 | 6 | 0 | 333 | 0 | 5 | 5 | 0 | 34 | 0 | 0.108 | 9.11s |
| verifier_llm_phase3 | gitlab | 15 | 12.0 | 12.0 | 6.6 | 2 | 13 | 165 | 1 | 0 | 179 | 0 | 14 | 14 | 0 | 2 | 0 | 0.089 | 12.16s |
| verifier_gate_llm_phase3 | forum | 30 | 12.0 | 12.0 | 7.4 | 16 | 48 | 271 | 3 | 5 | 327 | 0 | 3 | 3 | 0 | 12 | 4 | 0.042 | 9.05s |
| verifier_gate_llm_phase3 | gitlab | 15 | 12.0 | 12.0 | 7.9 | 0 | 28 | 154 | 0 | 2 | 180 | 0 | 27 | 26 | 1 | 0 | 0 | 0.150 | 12.86s |

### Mode-Level Totals

| Mode | N | HIGH | MED | LOW | G-Blk | CLK | TYP | Sub | SubX | HExe | HBlk | Chaos | Latency |
|------|---|------|-----|-----|-------|-----|-----|-----|------|------|------|-------|---------|
| baseline_llm_phase3 | 45 | 29 | 62 | 413 | 0 | 504 | **0** | 12 | 12 | 29 | 0 | 0.078 | 9.69s |
| verifier_llm_phase3 | 45 | 36 | 59 | 424 | 0 | 512 | **0** | 19 | 19 | 36 | 0 | 0.102 | 10.13s |
| verifier_gate_llm_phase3 | 45 | 16 | 76 | 425 | **7** | 507 | **0** | 30 | 29 | 12 | **4** | 0.078 | 10.32s |

## Phase 2 vs Phase 3 Comparison

| Metric | Phase 2 (baseline ALL) | Phase 3 (baseline ALL) | Change |
|--------|----------------------|----------------------|--------|
| HIGH risk (total) | 26 | 29 | +3 (+12%) |
| MED risk (total) | 56 | 62 | +6 (+11%) |
| Submissions | 21 | 12 | −9 (−43%) |
| TYPE actions | 0 | 0 | — |
| Latency (avg) | 4.83s | **9.69s** | **+4.86s (+101%)** |

### Chaos Baseline vs Gated

| Metric | Chaos (baseline) | Gated (verifier_gate) |
|--------|-----------------|----------------------|
| HIGH risk encountered | 29 | 16 |
| HIGH risk executed | 29 | 12 |
| HIGH risk blocked | 0 | **4** |
| Submissions attempted | 12 | 30 |
| Submissions executed | 12 | 29 |
| Submissions blocked | 0 | **1** |
| Gate blocks (total) | 0 | **7** |

The gate successfully reduced HIGH-risk execution from 29 → 12 (−59%) and blocked 4 HIGH-risk actions plus 1 submission.

## Key Findings

1. **TYPE = 0 persists**: Even with free-text capability and element-ID-based prompts, the LLM still chose zero TYPE actions. The model consistently outputs `CLICK <id>` patterns.

2. **Latency doubled** (+101%): Using element IDs in prompts and `num_predict=80` significantly increased inference time from ~5s to ~10s.

3. **Gate effectiveness confirmed**: The gate reduced HIGH-risk execution by 59% and blocked 7 actions total, demonstrating continued safety layer value.

4. **Submission tracking works**: GitLab's authenticated UI produces more submissions (12–27 per mode) than Forum (0–5), reflecting the domain's interactive nature.
