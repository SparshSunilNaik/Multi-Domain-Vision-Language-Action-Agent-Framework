# Phase 1 Final Analysis

## Confirmation of Constraints

- **Click-Only Architecture:** Throughout Phase 1 (including v2), the LLM agent output was strictly limited to `"click <index>"` actions. TYPE actions were purposely excluded to enforce an isolated environment for understanding baseline behavior under clicking navigation.
- **Baseline Risk Logging Fix:** In `experiment_runner_llm.py`, temporary scoping of `RiskScorer` successfully implemented passive scoring in `baseline_llm` (without invoking `RiskScorer.gate()` or altering agent progression). The baseline measurement artifact relies purely on structural instrumentation updates.

## Key Comparisons

### Baseline vs. Verifier (Structure Enforcement)
- The raw `baseline_llm` and `verifier_llm` profiles share identical risk encounters (e.g., `1.1` High Risk on Forum tasks). The core divergence is `blocked_verifier` triggering correctly under `verifier_llm` for invalid DOM access or tight step repetition without hallucinating missing nodes. 

### Verifier vs. Verifier_Gate_LLM (Policy Gates)
- On Forum tasks, the `verifier_gate_llm` explicitly curbed HIGH risk executions (`0.6±0.9` vs baseline/verifier values of `1.1`), producing `0.2±0.4` gate blocks per run. The 50% odd/even drop rate applied by `RiskScorer` successfully reduced final risk volume while providing the LLM safe recovery paths.

### Forum vs. GitLab (Domain Variability)
- **Latency Differences:** Due to GitLab’s deeply nested DOM elements contributing robustly to token bulk in prompt construction, GitLab consistently required double inference latency (~`5.5-7.0`s versus `2.5-3.8`s in Forum).
- **Risk Differences:** GitLab presents structurally low HIGH risk parameters when the session operates authentically (zero HIGH clicks reported per run), but invokes abundant MEDIUM queries involving structure mutations (`1.1` to `1.9` actions). Forum prominently highlights HIGH-risk targets explicitly in the masthead navigation (`Sign Up`, `Log Out`).

## Conclusion Statement

"Phase 1 (Click-Only) is now complete and stable. Ready to proceed to Phase 2 (TYPE support)."
