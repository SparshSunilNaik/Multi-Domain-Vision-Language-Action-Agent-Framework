# Phase 1 (v2) Final Summary

## Overview

The `baseline_llm` experiment was updated to properly log risk levels without altering its underlying logic (actions are scored but bypassing still applies). Sample size was scaled to **30 Forum** and **15 GitLab** tasks (135 total runs). Two new proxy metrics, `new_page_rate` and `max_same_url_streak`, were added to track behavioral stuckness.

## Aggregate Results

| Mode | Domain | Steps | Reward | URLs | High Risk | Med Risk | Low Risk | V-Blk | G-Blk | Latency (s) | NPR | Max Streak |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| baseline_llm | forum | 11.9±0.4 | 11.9±0.4 | 6.2±1.7 | 1.1±1.1 | 2.0±1.6 | 7.5±1.9 | 0.0±0.0 | 0.0±0.0 | 2.54±0.80 | 0.53±0.16 | 3.8±1.9 |
| baseline_llm | gitlab | 12.0±0.0 | 12.0±0.0 | 6.9±1.9 | 0.1±0.3 | 1.5±1.5 | 9.6±2.5 | 0.0±0.0 | 0.0±0.0 | 5.38±0.76 | 0.57±0.19 | 4.7±2.5 |
| verifier_llm | forum | 12.0±0.0 | 12.0±0.0 | 7.0±1.6 | 1.1±1.2 | 1.2±1.0 | 8.9±1.4 | 0.1±0.3 | 0.0±0.0 | 3.62±0.89 | 0.58±0.15 | 3.3±1.3 |
| verifier_llm | gitlab | 12.0±0.0 | 12.0±0.0 | 7.2±1.9 | 0.0±0.0 | 1.9±2.1 | 10.1±2.1 | 0.0±0.0 | 0.0±0.0 | 7.08±1.79 | 0.58±0.19 | 3.5±1.1 |
| verifier_gate_llm | forum | 12.0±0.0 | 12.0±0.0 | 6.7±1.7 | 0.6±0.9 | 1.5±1.3 | 8.8±1.7 | 0.1±0.3 | 0.2±0.4 | 3.78±0.59 | 0.55±0.16 | 3.8±1.7 |
| verifier_gate_llm | gitlab | 12.0±0.0 | 12.0±0.0 | 6.5±1.8 | 0.0±0.0 | 1.1±1.0 | 10.7±1.0 | 0.3±0.8 | 0.0±0.0 | 6.00±1.05 | 0.51±0.16 | 4.5±2.1 |

*Note on metrics: NPR = `new_page_rate`, Max Streak = `max_same_url_streak`.*

## Key Observations

1. **Baseline Logging Fixed:** `baseline_llm` now successfully reflects risk counts! We observed `1.1±1.1` HIGH risk elements clicked per Forum task, confirming the underlying behavior exists without the logging gap.
2. **Comparable Risk Encounters:** Across `baseline_llm` and `verifier_llm`, the raw quantity of HIGH encounters is similar (`1.1±1.1` vs `1.1±1.2`). This validates our hypothesis that the `baseline_llm` was encountering the same risks, just not instrumenting them.
3. **Exploration Stability:** The agent changes pages roughly half the time (`NPR` ~0.55), with a maximum streak of clicking within the same URL reaching roughly 3-4 steps across domains and modes.
