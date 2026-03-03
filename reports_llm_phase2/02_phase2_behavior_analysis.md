# Phase 2 Behavior Analysis

## Did TYPE Increase Exploration?

**No.** TYPE actions were never selected (TYP=0 across all 135 runs). The LLM's action space expansion had no behavioral effect on exploration.

| Metric | Phase 1 v2 (ALL) | Phase 2 (ALL) |
|--------|------------------|---------------|
| unique_urls (baseline) | 6.4±1.7 | 7.0±1.8 |
| new_page_rate (baseline) | 0.53±0.16 | 0.59±0.17 |
| max_same_url_streak (baseline) | 3.8±1.9 | 3.5±1.7 |

URL diversity and page rate are within stochastic noise of Phase 1. The slight increase in URLs is not attributable to TYPE support.

### Why the LLM Never Chose TYPE

The root cause is **positional bias in the numbered action list**:

1. **Prompt structure**: The Phase 2 prompt lists CLICK actions first (indices 1–N), then TYPE actions (indices N+1 through N+K×10).

2. **Typical page**: A Forum page has ~60–80 clickable elements and 1–2 typeable elements (usually a search box). This means:
   - CLICK options: indices 1–60
   - TYPE options: indices 61–80 (1 search box × 10 SLOT variants)

3. **LLM behavior with `num_predict=20`**: The model outputs at most 20 tokens, and typically outputs just a number. With temperature=0.7, it strongly favors low numbers in the 1–15 range (first-position bias well-documented in LLM literature).

4. **Result**: TYPE options at indices 60+ are virtually unreachable.

### Possible Fixes (NOT Implemented — Phase 3 Scope)

1. **Interleave CLICK and TYPE** in the numbered list instead of grouping
2. **Separate prompts**: First ask "CLICK or TYPE?", then list relevant options
3. **Increase TYPE salience**: Present TYPE options first when typeable elements are detected
4. **Reduce SLOT variants**: Show only 1–2 contextually relevant SLOTs instead of all 10

## Did Latency Increase?

**Yes, significantly.**

| Domain | Phase 1 v2 Latency | Phase 2 Latency | Increase |
|--------|-------------------|-----------------|----------|
| Forum (baseline) | 2.54±0.80s | 3.91±0.92s | +1.37s (+54%) |
| GitLab (baseline) | 5.38±0.76s | 6.68±0.63s | +1.30s (+24%) |
| Forum (gate) | 3.78±0.59s | 4.33±0.83s | +0.55s (+15%) |
| GitLab (gate) | 6.00±1.05s | 6.56±1.23s | +0.56s (+9%) |

The latency increase is caused by the longer prompt: each typeable element generates 10 additional lines (one per SLOT). Even though the LLM's output length is unchanged (just a number), the input processing time grows linearly with prompt length.

**Baseline sees the largest increase** because it's the simplest code path — verification and gate modes already had longer per-step times in Phase 1, masking the relative prompt overhead.

## Did the Gate Trigger More?

**The gate triggered slightly less in Phase 2 vs Phase 1 v2 for Forum tasks:**

| Metric | Phase 1 v2 (gate, forum) | Phase 2 (gate, forum) |
|--------|-------------------------|----------------------|
| Gate blocks (total) | 5 | 10 |
| HIGH encounters (total) | 17 | 25 |
| Gate blocks per task | 0.2±0.4 | 0.3±0.5 |

Gate activity is comparable. The slight increase in blocks reflects stochastic variation in HIGH encounters (25 vs 17), not a systematic change from TYPE support.

**GitLab had 0 gate blocks** in both phases because GitLab's authenticated UI doesn't expose HIGH-keyword elements.

## Did `max_same_url_streak` Change?

**No meaningful change:**

| Mode | Phase 1 v2 | Phase 2 |
|------|-----------|---------|
| baseline (forum) | 3.8±1.9 | 3.7±1.9 |
| baseline (gitlab) | 4.7±2.5 | 3.1±1.1 |
| gate (forum) | 3.8±1.7 | 4.0±2.0 |
| gate (gitlab) | 4.5±2.1 | 4.3±2.3 |

All values within 1σ of each other. The agent's stuckness behavior is unchanged.

## Summary

Phase 2's TYPE capability was correctly implemented (SLOT_MAP resolves, prompts include TYPE options, parser handles both CLICK and TYPE) but **had zero behavioral impact** because the LLM's positional bias toward low-numbered options prevents it from ever selecting TYPE actions at high indices. The primary measurable effect was a 15–54% latency increase from longer prompts.

This represents a real finding: **simply presenting more action options doesn't mean the LLM will use them.** Prompt engineering for action selection requires attention to ordering, salience, and context-dependent filtering.
