# Autonomy Escalation Analysis — Phase 1 → 2 → 3

## Risk Growth Across Phases

### HIGH Risk Encounters (total, baseline mode, ALL domains)

| Phase | HIGH Total | HIGH/Task | Change |
|-------|-----------|-----------|--------|
| Phase 1 v2 | 35 | 0.78 | — |
| Phase 2 | 26 | 0.58 | −26% |
| Phase 3A | 29 | 0.64 | +12% vs P2 |

HIGH risk encounters are remarkably stable across phases (26–35 total, 0.58–0.78/task). The noise band suggests these are driven by the stochastic nature of navigation rather than capability expansion.

### HIGH Risk Encounters (verifier_gate mode)

| Phase | HIGH Encountered | HIGH Executed | HIGH Blocked | Block Rate |
|-------|-----------------|---------------|--------------|------------|
| Phase 1 v2 | 17 | ~12 | ~5 | ~29% |
| Phase 2 | 25 | ~15 | ~10 | ~40% |
| Phase 3A | 16 | 12 | **4** | **25%** |

The gate consistently blocks 25–40% of HIGH-risk actions across all phases.

### MEDIUM Risk Encounters (total, baseline, ALL)

| Phase | MED Total | MED/Task |
|-------|-----------|----------|
| Phase 1 v2 | 84 | 1.87 |
| Phase 2 | 56 | 1.24 |
| Phase 3A | 62 | 1.38 |

MEDIUM risk remains stable at 1.2–1.9/task. Variation is within stochastic noise.

## Gate Intervention Growth

| Phase | Gate Blocks (gate mode) | Verifier Blocks (gate mode) |
|-------|------------------------|----------------------------|
| Phase 1 v2 | 5 | 7 |
| Phase 2 | 10 | 4 |
| Phase 3A | **7** | 3 |

Gate interventions are consistent at 5–10 per full experiment run. There is no systematic escalation of gate activity with increased autonomy, because the LLM's behavior remains primarily click-based.

## Latency Growth

| Phase | Forum Baseline | GitLab Baseline | Overall |
|-------|---------------|-----------------|---------|
| Phase 1 v2 | 2.54s | 5.38s | 3.49s |
| Phase 2 | 3.91s | 6.68s | 4.83s |
| Phase 3A | **8.31s** | **12.44s** | **9.69s** |

**Phase 3 latency is 2.8× Phase 1.** The primary drivers:
1. **Phase 2**: Longer prompts from TYPE+SLOT options (+40%)
2. **Phase 3**: Element-ID-based prompt format + `num_predict=80` (+100%)

GitLab is consistently ~1.5× slower than Forum due to deeper DOM structures generating more accessibility tree elements.

## Exploration Metrics

### Unique URLs

| Phase | Baseline URLs/Task | Gate URLs/Task |
|-------|-------------------|----------------|
| Phase 1 v2 | 6.4 | 6.6 |
| Phase 2 | 7.0 | 6.9 |
| Phase 3A | 6.7 | **7.6** |

The gate mode in Phase 3A shows slightly higher exploration (7.6 URLs/task) — possibly because gate blocks force alternative navigation paths.

### max_same_url_streak

| Phase | Baseline Streak | Gate Streak |
|-------|----------------|-------------|
| Phase 1 v2 | 3.8 | 3.8 |
| Phase 2 | 3.5 | 4.1 |
| Phase 3A | ~4.0 | ~4.0 |

Streak values are stable at ~3.5–4.0 across all phases and modes. The agent exhibits comparable stuckness behavior regardless of capability level.

## Summary

The autonomy escalation from Phase 1 → 3A reveals that **increased capability does not automatically translate to increased risk**. The primary measurable impact of expanding the action space has been:
1. **Latency increase** (2.8× from Phase 1 to Phase 3)
2. **Zero TYPE utilization** (LLM consistently prefers CLICK)
3. **Stable risk profile** (HIGH encounters stay within 0.6–0.8/task)
4. **Consistent gate effectiveness** (25–40% HIGH-risk blocking)

The LLM's behavior is fundamentally click-centric regardless of TYPE availability. Achieving actual TYPE usage requires orthogonal prompt engineering changes, not just capability expansion.
