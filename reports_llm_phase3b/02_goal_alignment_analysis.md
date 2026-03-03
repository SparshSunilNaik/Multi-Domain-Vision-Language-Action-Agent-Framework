# Goal Alignment Analysis — Phase 3B

## typed_when_expected Rate

31 of 45 tasks (69%) contained TYPE-keyword instructions (e.g., "search", "create", "name", "enter"). Despite this:

| Mode | Tasks with TYPE Keywords | Tasks that Typed | typed_when_expected Rate |
|------|------------------------|------------------|------------------------|
| baseline_llm_phase3b | 31 | 0 | **0.0%** |
| verifier_llm_phase3b | 31 | 0 | **0.0%** |
| verifier_gate_llm_phase3b | 31 | 0 | **0.0%** |

The `typed_when_expected` rate is **0% across all modes**. The LLM never generates TYPE actions regardless of instruction content or TYPE promotion in the prompt.

### Why typed_when_expected = 0

1. **Format bias**: The model consistently produces `CLICK <id>` format. Even with `num_predict=120`, the model outputs click-format responses.

2. **TYPE promotion insufficient**: Listing typeable elements first changes the prompt order but not the model's generation pattern. The `CLICK` keyword appears as an option format and the model gravitates toward it.

3. **No explicit instruction to type**: While the prompt says "TYPE <id> \"text\"" is an option, it doesn't strongly incentivize typing over clicking. A more directive prompt (e.g., "You MUST type in the search box") would be needed.

## Goal Alignment Score Distribution

`goal_alignment_score = (keywords matching element name) / (total instruction keywords)`

| Mode | Mean Alignment | Domain Breakdown |
|------|---------------|-----------------|
| baseline_llm_phase3b | 0.007 | Forum: 0.010, GitLab: 0.001 |
| verifier_llm_phase3b | 0.010 | Forum: 0.011, GitLab: 0.008 |
| verifier_gate_llm_phase3b | 0.010 | Forum: 0.012, GitLab: 0.007 |

Alignment scores are extremely low (0.7–1.2%), reflecting that:
- WebArena task instructions use abstract concepts ("count of comments", "most upvoted post")
- Element names are concrete UI labels ("Home", "New", "Sort by: Hot")
- Lexical overlap between abstract instructions and concrete elements is minimal

### Chaos vs Gated Alignment

| Metric | Chaos (baseline) | Gated |
|--------|-----------------|-------|
| Alignment (forum) | 0.010 | 0.012 |
| Alignment (gitlab) | 0.001 | 0.007 |
| Alignment (ALL) | 0.007 | 0.010 |

The gated mode shows marginally higher alignment (+43% overall), possibly because gate blocks redirect the agent to different elements that happen to have slightly better keyword overlap. However, these differences are within noise for such low absolute values.

## What Would Improve Goal Alignment

1. **Semantic matching**: Use embedding-based similarity instead of lexical overlap. Words like "upvotes" in instructions should match "Vote" in elements.

2. **Multi-step planning**: Track whether a sequence of actions collectively advances toward the goal, not just individual element matches.

3. **Task decomposition**: Break instructions like "find the post with most upvotes in the science forum" into sub-goals: (a) navigate to science forum, (b) sort by upvotes, (c) identify top post.

4. **Stronger TYPE directive**: When `should_promote_type()` is true, add explicit text like "You should type text into one of the typeable fields to complete this task."

## Conclusion

The goal alignment metric reveals a fundamental limitation: **simple lexical matching between task instructions and UI elements produces near-zero scores** because they operate at different semantic levels. Future phases should explore semantic alignment or task-decomposition approaches for meaningful goal tracking.
