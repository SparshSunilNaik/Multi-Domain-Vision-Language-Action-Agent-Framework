# Phase 3B Summary — Instruction-Conditioned Autonomy

## Overview

Phase 3B upgraded the LLM agent from reactive autonomy to **goal-directed autonomy** with:
- **Planning scaffold**: PLAN + ACTION format in prompts
- **Action history**: Last 3 actions shown for context
- **TYPE promotion**: Instruction keywords reorder elements to prioritize typing
- **Goal alignment scoring**: Lexical match between instruction and chosen element

135 tasks (3 modes × 45 tasks: 30 Forum + 15 GitLab), `qwen3:8b`, temp=0.7, `num_predict=120`.

## Aggregate Results

| Mode | Domain | N | Steps | Reward | URLs | HIGH | MED | LOW | V-Blk | G-Blk | CLK | TYP | Sub | HExe | HBlk | Plan | Align | Latency |
|------|--------|---|-------|--------|------|------|-----|-----|-------|-------|-----|-----|-----|------|------|------|-------|---------|
| baseline_llm_phase3b | forum | 30 | 11.9 | 11.8 | 6.4 | 24 | 58 | 236 | 0 | 0 | 318 | 0 | 2 | 24 | 0 | 0 | 0.010 | 13.11s |
| baseline_llm_phase3b | gitlab | 15 | 12.0 | 12.0 | 6.9 | 1 | 18 | 161 | 0 | 0 | 180 | 0 | 22 | 1 | 0 | 2 | 0.001 | 17.83s |
| verifier_llm_phase3b | forum | 30 | 12.0 | 11.9 | 7.0 | 22 | 45 | 268 | 12 | 0 | 323 | 0 | 4 | 22 | 0 | 0 | 0.011 | 15.82s |
| verifier_llm_phase3b | gitlab | 15 | 12.0 | 12.0 | 7.3 | 0 | 15 | 163 | 0 | 0 | 178 | 0 | 17 | 0 | 0 | 1 | 0.008 | 19.39s |
| verifier_gate_llm_phase3b | forum | 30 | 12.0 | 12.0 | 6.7 | 25 | 45 | 258 | 6 | 7 | 315 | 0 | 3 | 18 | **7** | 1 | 0.012 | 15.09s |
| verifier_gate_llm_phase3b | gitlab | 15 | 12.0 | 12.0 | 6.9 | 0 | 16 | 164 | 0 | 0 | 180 | 0 | 19 | 0 | 0 | 0 | 0.007 | 17.71s |

### Mode-Level Totals

| Mode | N | HIGH | MED | LOW | G-Blk | CLK | TYP | Sub | HExe | HBlk | Plan | Align | Latency |
|------|---|------|-----|-----|-------|-----|-----|-----|------|------|------|-------|---------|
| baseline_llm_phase3b | 45 | 25 | 76 | 397 | 0 | 498 | **0** | 24 | 25 | 0 | 2 | 0.007 | 14.69s |
| verifier_llm_phase3b | 45 | 22 | 60 | 431 | 0 | 501 | **0** | 21 | 22 | 0 | 1 | 0.010 | 17.01s |
| verifier_gate_llm_phase3b | 45 | 25 | 61 | 422 | **7** | 495 | **0** | 22 | 18 | **7** | 1 | 0.010 | 15.96s |

## Phase 3A vs Phase 3B Comparison

| Metric | Phase 3A (baseline ALL) | Phase 3B (baseline ALL) | Change |
|--------|------------------------|------------------------|--------|
| HIGH risk | 29 | 25 | −4 (−14%) |
| MED risk | 62 | 76 | +14 (+23%) |
| Submissions | 12 | **24** | **+12 (+100%)** |
| TYPE actions | 0 | 0 | — |
| Gate blocks (gate mode) | 7 | **7** | — |
| HIGH blocked (gate mode) | 4 | **7** | +3 (+75%) |
| Latency | 9.69s | **14.69s** | **+5.0s (+52%)** |
| Plans present | N/A | 2 | NEW |
| Goal alignment | N/A | 0.007 | NEW |

### Key Changes from Phase 3A

1. **Submissions doubled** (12 → 24): The task-instruction-aware prompt helps the LLM navigate to submission-related UI elements more often.

2. **Gate blocks HIGH more effectively**: 7 HIGH-risk actions blocked in Phase 3B gate mode (vs 4 in Phase 3A), reducing HIGH execution from 25 → 18 (−28%).

3. **Latency increased 52%**: The longer prompt (PLAN scaffold + action history + TYPE promotion) adds ~5s per inference call.

4. **TYPE still = 0**: Despite TYPE promotion and instruction-keyword detection (31/45 tasks have TYPE keywords), the LLM never generates `TYPE <id> "<text>"` format.

5. **Planning rarely generated**: Only 2–4 plan lines across all 540 steps, suggesting the model's 120-token budget is mostly consumed by reasoning tokens before reaching the PLAN/ACTION output.

## 31/45 Tasks Had TYPE Keywords

The `should_promote_type()` function detected TYPE-relevant keywords in 31 of 45 tasks (69%). These tasks had typeable elements listed BEFORE clickable elements in the prompt. Despite this promotion, TYP=0.

## Conclusion

Phase 3B's instruction conditioning **increased submissions** (+100%) and **improved gate effectiveness** (+75% HIGH blocks) but did **not achieve TYPE action generation**. The planning scaffold was rarely utilized. The primary behavioral change was more goal-relevant navigation leading to submission UI elements.
