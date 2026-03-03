# Phase 2 Action Distribution Analysis

## Overall Action Type Distribution

| Mode | Total Actions | CLICK | TYPE | %CLICK | %TYPE |
|------|--------------|-------|------|--------|-------|
| baseline_llm_phase2 | 498 | 498 | 0 | **100.0%** | 0.0% |
| verifier_llm_phase2 | 509 | 509 | 0 | **100.0%** | 0.0% |
| verifier_gate_llm_phase2 | 501 | 501 | 0 | **100.0%** | 0.0% |
| **Total** | **1508** | **1508** | **0** | **100.0%** | **0.0%** |

The action distribution is 100% CLICK across all modes and domains. TYPE support was available but never utilized by the LLM.

## Risk Distribution by Action Type (CLICK only)

Since all actions are CLICK, the risk breakdown reflects click behavior exclusively:

### Forum Tasks (30 per mode)

| Mode | HIGH | MED | LOW | H/task | M/task | L/task |
|------|------|-----|-----|--------|--------|--------|
| baseline_llm_phase2 | 25 | 40 | 260 | 0.8±1.1 | 1.3±0.9 | 8.7±1.8 |
| verifier_llm_phase2 | 37 | 63 | 235 | 1.2±1.2 | 2.1±1.5 | 7.8±1.7 |
| verifier_gate_llm_phase2 | 25 | 55 | 253 | 0.8±1.1 | 1.8±1.4 | 8.4±1.9 |

### GitLab Tasks (15 per mode)

| Mode | HIGH | MED | LOW | H/task | M/task | L/task |
|------|------|-----|-----|--------|--------|--------|
| baseline_llm_phase2 | 1 | 16 | 156 | 0.1±0.3 | 1.1±1.1 | 10.4±1.7 |
| verifier_llm_phase2 | 0 | 26 | 148 | 0.0±0.0 | 1.7±1.8 | 9.9±2.0 |
| verifier_gate_llm_phase2 | 0 | 18 | 160 | 0.0±0.0 | 1.2±1.2 | 10.7±1.2 |

### Key Observations

1. **Forum has higher HIGH risk** (0.8–1.2/task) than GitLab (0.0–0.1/task) because Forum's header persistently displays "Sign up" and "Log out" links.

2. **Gate reduces HIGH encounters from 37 (verifier) to 25 (gate)** on Forum. This 32% reduction occurs because gate blocks force fallback to safer elements, which in turn influences subsequent page states.

3. **GitLab is MEDIUM-dominant** (1.1–1.7/task) due to "Create", "New project", and "Edit" elements in the UI.

## Submission Attempt Analysis

| Mode | Domain | Total Submissions | Gated Submissions | %Gated |
|------|--------|-------------------|-------------------|--------|
| baseline_llm_phase2 | forum | 1 | 0 | 0% |
| baseline_llm_phase2 | gitlab | 20 | 0 | 0% |
| verifier_llm_phase2 | forum | 0 | 0 | — |
| verifier_llm_phase2 | gitlab | 19 | 0 | 0% |
| verifier_gate_llm_phase2 | forum | 2 | 0 | 0% |
| verifier_gate_llm_phase2 | gitlab | 16 | 0 | 0% |

### Why GitLab Has More Submissions

GitLab pages feature prominent "Save changes", "Create project", and "Submit" buttons. The LLM clicks these as part of normal page navigation. Forum pages rarely expose submission buttons to unauthenticated users.

### Why Gated Submissions = 0

The `gated_submission_attempts` counter increments only when a submission-like click is both:
1. Classified as HIGH risk by `RiskScorer.score()`
2. Actually blocked by `RiskScorer.gate()`

Most submission buttons (e.g., "Create project") match `SUBMISSION_KEYWORDS` but are classified as **MEDIUM** (the "create" keyword is in `MEDIUM_KEYWORDS`), not HIGH. The gate only blocks MEDIUM every 5th encounter, and even when it does, it's not counted as a "gated submission" unless the element also matched `SUBMISSION_KEYWORDS`. This is a taxonomy overlap issue.

Only "Submit" and "Confirm" are in both `SUBMISSION_KEYWORDS` and `HIGH_KEYWORDS`. These buttons are rare in normal navigation.

## Hypothetical TYPE Risk Distribution

If the LLM had chosen TYPE actions, the RiskScorer would have classified them as follows (based on `safe_runner.py` logic):

| Context | Risk Level | Reason |
|---------|-----------|--------|
| TYPE on login/registration page | **HIGH** | URL matches `AUTH_URL_PATTERNS` |
| TYPE on any other page | **MEDIUM** | All TYPE on non-auth pages = MEDIUM |

This means TYPE actions would have increased MEDIUM counts proportionally and potentially triggered gate blocks (MEDIUM blocks every 5th encounter). Since TYPE was never executed, this effect remains theoretical.

## Conclusion

Phase 2 demonstrates that **expanding the action space does not guarantee utilization**. The LLM's selection behavior is governed by prompt structure and positional bias, not just availability. The safety infrastructure (Verifier, RiskScorer, Gate) correctly handles TYPE actions in code, but was never exercised for TYPE in practice. Future work should address prompt ordering strategies to encourage TYPE action selection when contextually appropriate.
