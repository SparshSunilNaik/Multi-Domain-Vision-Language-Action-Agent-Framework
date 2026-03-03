# Planning Behavior — Phase 3B

## Plan Presence Rate

The Phase 3B prompt requests output in the format:
```
PLAN: <one sentence about what to do next>
ACTION: CLICK <id> or TYPE <id> "<text>"
```

| Mode | Total Steps | Steps with PLAN | Plan Rate |
|------|------------|----------------|-----------|
| baseline_llm_phase3b | ~540 | 2 | **0.4%** |
| verifier_llm_phase3b | ~540 | 1 | **0.2%** |
| verifier_gate_llm_phase3b | ~540 | 1 | **0.2%** |
| **Total** | **~1620** | **4** | **0.2%** |

Plans appeared in only **4 out of ~1620 steps** (0.2%). The planning scaffold was almost entirely ignored by the model.

## Average Plan Length

| Mode | Plans Present | Avg Plan Length (chars) |
|------|-------------|----------------------|
| baseline_llm_phase3b | 2 | ~40–60 chars (estimated) |
| verifier_llm_phase3b | 1 | ~40–60 chars |
| verifier_gate_llm_phase3b | 1 | ~40–60 chars |

With so few plans, statistical analysis is not meaningful. The plans that did appear were brief single sentences.

## Why Plans Are Rare

### 1. Token Budget Competition

With `num_predict=120` tokens, the model must generate both PLAN and ACTION. The `qwen3:8b` model with `temperature=0.7` appears to:
- Sometimes generate internal reasoning (thinking tokens) before output
- Jump directly to `CLICK <id>` without producing the PLAN prefix
- Hit the token limit before completing the PLAN + ACTION structure

### 2. Format Compliance vs Content

The model produces syntactically valid CLICK actions most of the time (parsed=True rate is high), but skips the PLAN prefix. This suggests the model prioritizes the "actionable" part of the output over the "reasoning" part.

### 3. Model Size Limitation

`qwen3:8b` is a relatively small model. Instruction-following at this parameter count often produces abbreviated outputs. Larger models (30B+) would likely show better format compliance with multi-part output structures.

## Planning Did Not Change Behavior

Comparing Phase 3A (no planning) vs Phase 3B (planning scaffold):

| Metric | Phase 3A | Phase 3B | Change |
|--------|---------|---------|--------|
| Unique URLs/task (baseline) | 6.7 | 6.6 | −0.1 |
| TYPE actions | 0 | 0 | — |
| HIGH risk/task (baseline) | 0.64 | 0.56 | −0.08 |
| Submissions (baseline) | 12 | 24 | +12 |

The **doubling of submissions** is the only clear behavioral change, and this is more likely attributable to the **instruction-conditioning** (explicit GOAL in prompt) and **TYPE promotion** (element reordering) than to the planning scaffold itself, since plans were generated in <1% of steps.

## Recommendations for Improving Planning

1. **Two-stage generation**: First query the LLM for a plan only, then query again with the plan + elements for an action. This doubles latency but ensures plans are generated.

2. **Increase `num_predict`**: Setting to 200+ would give more token budget for PLAN + ACTION. Trade-off: higher latency.

3. **Simplify PLAN format**: Instead of requesting a sentence, ask for a single word describing the intent (e.g., "navigate", "search", "submit", "explore").

4. **Use larger model**: `qwen3:14b` or `qwen3:32b` would likely produce better format compliance. Trade-off: significantly higher latency and memory requirements.

5. **Few-shot examples**: Add 2–3 example PLAN+ACTION pairs in the prompt to demonstrate the expected format. Trade-off: longer prompts.

## Conclusion

The planning scaffold in Phase 3B was a **near-zero-impact intervention** — the model generates plans in only 0.2% of steps. The behavioral improvement in submissions (+100% vs Phase 3A) is driven by instruction conditioning and TYPE promotion, not planning. Effective planning requires either a larger model, multi-stage prompting, or few-shot examples to achieve meaningful plan generation rates.
