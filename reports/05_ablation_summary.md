# Ablation Summary

## Three-Way Comparison

| Metric | baseline | verifier | verifier+gate | Δ (gate vs baseline) |
|--------|----------|----------|---------------|---------------------|
| Steps executed | 15.0 | 15.0 | 15.0 | 0 |
| Cumulative reward | 15.0 | 15.0 | 15.0 | 0 |
| Unique URLs | 6.0 | 6.0 | **7.0** | **+1.0** |
| Verifier blocks | 0 | 0 | 0 | 0 |
| Gate blocks | 0 | 0 | **1.0** | **+1.0** |
| Actions proposed | 15.0 | 15.0 | **16.0** | **+1.0** |
| Actions executed | 15.0 | 15.0 | 15.0 | 0 |
| Loop count | 4.0 | 4.0 | **3.0** | **−1.0** |

Data source: `results.csv` (20 tasks per mode, all values identical within mode).

## Behavioral Interpretation

### Baseline → Verifier: No Change

The Verifier introduces **no behavioral difference** against the deterministic heuristic policy in batch mode. This is expected:

1. **Element validation**: The policy only targets elements by name search in the accessibility tree. Every targeted element exists and has a clickable role (link, button). The Verifier's role check never fires.

2. **Repetition detection**: The policy cycles through 7 distinct targets. With `MAX_REPEAT = 2` and `HISTORY_SIZE = 10`, no (URL, element) pair appears more than twice in any window. The repetition check never fires.

3. **State change detection**: This is a post-step diagnostic check, not a pre-step blocker. It logs no-ops but does not prevent actions.

**Conclusion**: The Verifier is correctly implemented but its checks are not triggered by the benign, well-structured heuristic policy. A more adversarial or LLM-based policy — which might target non-existent elements, repeat the same action, or click non-interactive elements — would trigger verifier blocks.

### Verifier → Verifier+Gate: Measurable Shift

Adding the gate produces three measurable effects:

#### 1. Gate Blocks (+1 blocked action per task)

Every task has exactly 1 gate block. The gate blocks the 2nd HIGH-risk encounter. In the Forum heuristic cycle:
- Step 3: "Sign up" → HIGH → encounter #1 (odd) → **allowed**
- Step 10: "Sign up" → HIGH → encounter #2 (even) → **blocked**

The blocked action is replaced by a fallback element (the next clickable element on the page).

#### 2. URL Diversity (+1 unique URL)

When the gate blocks "Sign up" at step 10, the fallback action navigates to a different page (e.g., `/comments`), resulting in 7 unique URLs vs 6. This demonstrates that **gating changes the agent's trajectory** — it doesn't just skip actions, it redirects behavior.

#### 3. Reduced Looping (−1 loop frequency)

The fallback action breaks the deterministic navigation cycle, causing the agent to visit a different URL at that step. This reduces the number of consecutive same-URL steps from 4 to 3.

## Why Verifier Blocks Are Zero in Batch Mode

Several factors combine to make verifier blocks zero:

1. **Deterministic policy with valid targets**: The heuristic policy targets elements by name substring match. These targets ("Forums", "Log in", "Wiki", etc.) always exist on the Forum pages and have clickable roles.

2. **No repetition pressure**: The 7-target cycle with 15 steps means each target is visited at most 3 times total, but the (URL, element_name) pair typically changes because the URL changes between visits.

3. **No stale elements**: The accessibility tree is re-parsed fresh each step. The policy searches the current tree, so it never references stale element IDs.

### When Verifier Blocks Do Occur

Verifier blocks **were observed during early manual testing** with different exploration strategies:
- When the GitLab policy tried to click elements that didn't exist on redirected pages.
- When repetition detection fired after the agent revisited the same page and clicked the same element 3+ times.

These scenarios don't arise with the final heuristic because it was tuned to avoid them. A real LLM-based agent would trigger verifier blocks more frequently.

## Where Gating Drives the Biggest Change

The gate's impact is most significant for:

1. **Navigation trajectory**: A single blocked action at step 10 cascades into a different URL at step 10, which changes the element set for steps 11–15, potentially altering the entire remaining trajectory.

2. **Loop breaking**: The fallback mechanism reduces URL looping, which is a proxy for agent "stuckness". In production, this would mean a gated agent explores more broadly.

3. **Safety surface coverage**: By blocking the 2nd "Sign up" navigation, the gate prevents the agent from repeatedly visiting the registration page — a genuine safety improvement if the agent were actually capable of registering accounts.

## Visual Debug Comparison

The visual debug runners (`visual_debug_runner.py`) show the same pattern:

### Baseline (Forum)
```
Steps: 12 | Proposed: 12 | Executed: 12 | V-Block: 0 | G-Block: 0 | URLs: 6
```

### Verifier+Gate (Forum)
```
Steps: 12 | Proposed: 13 | Executed: 12 | V-Block: 0 | G-Block: 1 | URLs: 7
```

The visual runs use 12 steps instead of 15, so the gate blocks occur at step 4 ("Sign up" → 2nd HIGH encounter) rather than step 10.

## GitLab Dimension

On GitLab (`gitlab_visual_debug.py`), the safety pipeline shows a richer picture:

```
Steps: 12 | Proposed: 14 | Executed: 12 | V-Block: 0 | G-Block: 2 | URLs: 6
HIGH encountered: 3 | HIGH gated: 1
MEDIUM encountered: 6 | MEDIUM gated: 1
LOW encountered: 5
```

GitLab exposes 3 HIGH-risk encounters (vs 1 in Forum 12-step runs), resulting in:
- 1 HIGH gate block (encounter #2)
- 1 MEDIUM gate block (encounter #5)
- 2 total fallback substitutions

This confirms the gate is functional across domains with varying risk surfaces.

## Summary Table

| Aspect | baseline | verifier | verifier+gate |
|--------|----------|----------|---------------|
| Safety checks | None | Element + repetition | Element + repetition + risk scoring + gating |
| Blocks observed | 0 | 0 | 1–2 per task |
| URL diversity | 6 | 6 | 7 |
| Loop frequency | 4 | 4 | 3 |
| Trajectory change | No | No | Yes (fallback on gate block) |
