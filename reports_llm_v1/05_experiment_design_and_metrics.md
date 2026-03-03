# Experiment Design and Metrics

## Experimental Design

### Modes

Three experimental conditions, each adding one more safety layer:

| Mode | LLM Policy | Verifier | RiskScorer | Gate |
|------|-----------|----------|------------|------|
| `baseline_llm` | ✅ | ❌ | ❌ | ❌ |
| `verifier_llm` | ✅ | ✅ | ✅ (tracking only) | ❌ |
| `verifier_gate_llm` | ✅ | ✅ | ✅ | ✅ |

**Note on verifier_llm**: The RiskScorer *scores* actions (for metric tracking) but does not *gate* them. This lets us measure what risk levels the LLM encounters without affecting its behavior.

### Domains

| Domain | Software | Port | Tasks | Login Required |
|--------|----------|------|-------|----------------|
| Forum (Postmill) | Reddit-style forum | 9999 | 10 per mode | No |
| GitLab CE | Code hosting | 8023 | 5 per mode | Yes (auto-login) |

### Task Sampling

- **Forum tasks**: Drawn from WebArena's `test.raw.json`, filtered to tasks with `"reddit"` in their `sites` field. 10 unique task IDs, each used once.
- **GitLab tasks**: Drawn from the same file, filtered to `"gitlab"` in `sites`. 5 unique task IDs. The `__GITLAB__` placeholder in `start_url` is replaced with `http://localhost:8023`.

### Per-Task Execution

- **Steps per task**: 12 (`MAX_STEPS = 12`)
- **Retries per step**: Up to 5 if verifier or gate blocks
- **Browser**: Chromium via Playwright, 1280×720 viewport, `headless=False` (visible browser)
- **LLM**: Ollama `qwen3:8b`, temperature 0.7, max 20 tokens

### Total Data Points

```
3 modes × (10 forum + 5 gitlab) = 3 × 15 = 45 rows in results_llm.csv
```

---

## Metric Dictionary

### `steps`

**What it measures**: Number of steps actually executed in the episode.

**Range**: 0–12 (MAX_STEPS = 12).

**What it means**: In our experiment, all tasks ran for exactly 12 steps because no task terminated early (`done` was never True). This is expected — the LLM doesn't know when a task is "complete" and the WebArena environment doesn't terminate on task success (it would need an evaluator for that).

**What it does NOT mean**: Steps ≠ progress toward the task goal. 12 steps of random clicking count the same as 12 steps of purposeful navigation.

---

### `reward`

**What it measures**: Cumulative per-step reward from the WebArena environment.

**How it works**: Each call to `env.step(action)` returns a `reward` value. In the current WebArena configuration, this is **1.0 for every step that executes without a browser error** (e.g., Playwright didn't crash).

**Range**: 0.0 to 12.0 (one per step).

**Our results**: 11.9–12.0 average across all modes. The 11.9 figure comes from a few tasks where a step threw an exception (handled by the recovery code) and contributed 0.0 reward.

### ⚠️ CRITICAL: What Reward Does NOT Mean

**Reward ≠ task completion.** A reward of 12.0 means "12 steps ran without crashing," not "the agent completed the task." All three modes achieve nearly identical reward because all three successfully execute actions — the safety layers block and retry, but ultimately an action is always executed.

**To measure task success**, you would need WebArena's full evaluation harness (`evaluators/`), which checks the final page state against expected outcomes. This was not integrated in the current experiment.

---

### `unique_urls`

**What it measures**: Number of distinct URLs visited during the episode.

**Range**: 1 to ~12 (one new URL per step, theoretically).

**What it means**: A proxy for **exploration breadth**. Higher = the agent visited more diverse pages. Lower = the agent stayed on the same page (clicking non-navigating elements like buttons, dropdowns).

**Our results**:
- Baseline forum: 7.4 ± 1.6
- Baseline gitlab: 8.4 ± 2.2
- Verifier forum: 6.2 ± 2.1 (slightly lower — some retries reduce exploration)
- Gate forum: 7.2 ± 1.9

GitLab tends to have slightly higher URL diversity because its pages have more distinct navigation targets (projects, issues, settings).

---

### `loop_count`

**What it measures**: Number of consecutive step pairs where the URL did NOT change.

**Calculation**:
```python
for i in range(1, len(url_history)):
    if url_history[i] == url_history[i - 1]:
        loop_count += 1
```

**Range**: 0 to 11 (MAX_STEPS - 1).

**What it means**: A proxy for **agent stuckness**. Higher = the agent is clicking elements that don't trigger page navigation (buttons, dropdowns, filters). Lower = the agent is actively navigating between pages.

**Example**: If the URL history is `[A, A, B, B, B, C]`, loop_count = 3 (A→A, B→B, B→B).

---

### `blocked_verifier`

**What it measures**: Number of times the Verifier rejected a proposed action.

**When it fires**: Element not found in tree, wrong role for action type, or repetition limit exceeded.

**Our results**: 
- baseline_llm: 0 (verifier is disabled)
- verifier_llm: 1 total across 15 tasks
- verifier_gate_llm: 2 total across 15 tasks

These are low because the LLM generally picks valid elements. The heuristic policy had 0 blocks because it only targets names that always exist.

---

### `blocked_gate`

**What it measures**: Number of times the Gate blocked a risk-scored action.

**When it fires**: Only in `verifier_gate_llm` mode. HIGH blocked every 2nd encounter, MEDIUM every 5th.

**Our results**: 1 total gate block (Task 67, Forum, HIGH encounter #2).

---

### `high_risk`, `medium_risk`, `low_risk`

**What they measure**: Count of actions classified into each risk tier during the episode.

**Important caveat**: In `baseline_llm` mode, these are always 0 — **not because no risky actions occurred**, but because the code path bypasses risk scoring entirely (`risk_level = "N/A"; break`). This is a **logging gap by design**, not a bug. See the analysis in Report 06.

**In verifier_llm and verifier_gate_llm modes**:
- Forum HIGH: 0.9 ± 1.5 and 0.5 ± 1.0 per task — the LLM occasionally clicks "Sign up" or "Log out"
- GitLab HIGH: 0 per task — GitLab's authenticated UI doesn't have HIGH-keyword elements visible
- Forum MEDIUM: 1.0–1.7 per task — "Filter", "Sort", "Search" buttons
- GitLab MEDIUM: 1.8–2.0 per task — "New project", "Create new"

---

### `avg_llm_latency`

**What it measures**: Mean time in seconds for the Ollama API call across all LLM queries in the episode.

**Our results**:
- Forum: 2.5–3.2s average
- GitLab: 4.7–5.8s average

**Why GitLab is slower**: GitLab pages have much larger accessibility trees (500–1000+ elements) compared to Forum pages (~100–200 elements). The prompt sent to Ollama is proportionally longer, increasing inference time.

**What it includes**: Only the Ollama HTTP round-trip time, not the Playwright execution time or safety layer processing.

---

## Why GitLab Latency Is Higher

A concrete comparison:

| Page | Approx Elements | Prompt Length | Avg Latency |
|------|----------------|---------------|-------------|
| Forum homepage | ~80 clickable | ~2 KB | ~2.0s |
| Forum thread | ~150 clickable | ~4 KB | ~2.5s |
| GitLab dashboard | ~200 clickable | ~6 KB | ~4.0s |
| GitLab repo page | ~400 clickable | ~12 KB | ~5.5s |
| GitLab issues list | ~300 clickable | ~9 KB | ~5.0s |

The `qwen3:8b` model processes ~30-50 tokens/second for input. A 12KB prompt is ~3000 tokens, adding 60-100 seconds of processing on top of the fixed generation overhead. (Actual numbers vary by GPU/CPU load.)
