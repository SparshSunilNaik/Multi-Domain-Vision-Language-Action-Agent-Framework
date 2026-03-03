# Metric Definitions

This glossary details every CSV metric explicitly for Phase 1 (v2) reporting:

## System Data
- **mode:** Operating phase of the runner (`baseline_llm`, `verifier_llm`, or `verifier_gate_llm`).
- **domain:** WebArena container domain processed (`forum` or `gitlab`).
- **task_id:** Unique identifier ID mapping precisely to the loaded `test.raw.json` tasks.

## Step Behaviors
- **steps:** Executed iterations processed by env step processing (capped at 12 steps).
- **reward:** The step-execution success return value provided per functional action (ranging 0.0 to 12.0 mapping purely on syntax validation tracking, NOT evaluating actual WebArena benchmark completions).
- **unique_urls:** The discrete count of unique browser endpoints rendered over an agent sequence history.
- **avg_llm_latency:** Average wall-time seconds consumed via Ollama query executions across a single task sequence.

## Safety Interventions (Counters)
- **blocked_verifier:** Explicit tracking count marking when structural rule exceptions stopped actions (DOM unfindable, missing properties, strict `10|2`-repetition cycles). 
- **blocked_gate:** Counting instance occurrences where the Tier Gate blocked execution (`HIGH` 50% thresholds and `MEDIUM` 20% thresholds).
- **actions_proposed:** The raw total of output intents (including those caught and immediately retried by safety mechanisms).
- **actions_executed:** Successful requests executed against Playwright without unhandling safety catches.
- **high_risk:** Fired counter matching keyword actions invoking risk rules (e.g. `"submit", "delete", "sign up"`).
- **medium_risk:** Fired counter tracking medium keyword invocations (e.g. `"search", "edit", "create"`).
- **low_risk:** Residual fallback mapping representing all unmarked actions executed safely.

## Phase 1 v2 Structural Additions:
- **new_page_rate:** Fractional percent (`0.0` - `1.0`) measuring how frequently consecutive operations resulted in DOM URL context differences. Measured uniquely as distinct pairs across the sequence timeline.
- **max_same_url_streak:** Integer sequence tracking the absolute longest consecutive streak of actions targeting the identical DOM Endpoint location (e.g. clicking 4 inline tabs in a row yields a value of 4).
