# System Overview

## What the System Is

**Safe WebArena Agent** is a safety-aware evaluation framework for web agents operating on realistic, locally-hosted web applications. It wraps the [WebArena](https://webarena.dev/) benchmark with deterministic safety layers — a **Verifier** and a **RiskScorer with Tiered Autonomy Gate** — that classify, validate, and conditionally block actions before execution.

The system runs entirely on a local macOS Apple Silicon machine using Docker containers for two WebArena domains:

| Domain | Software | Port | Image Arch |
|--------|----------|------|------------|
| Forum | Postmill (Reddit-style) | `localhost:9999` | arm64-native |
| GitLab | GitLab CE (pre-populated) | `localhost:8023` | amd64 (emulated via Rosetta) |

## What Problem It Solves

Web agents (VLAs, LLM-based browsing agents) can perform destructive or unauthorized actions — deleting repositories, submitting forms, creating accounts — without understanding the consequences. Current WebArena evaluation measures only task success, with no mechanism to detect or prevent harmful actions.

This framework addresses three gaps:

1. **Pre-execution validation** — The Verifier blocks structurally invalid actions (non-existent elements, wrong roles, repetition loops) before they reach the browser.
2. **Risk classification** — The RiskScorer assigns HIGH / MEDIUM / LOW risk levels based on element text keywords and URL patterns.
3. **Tiered autonomy gating** — A deterministic gate simulates human-approval policies: HIGH-risk actions are allowed 50% of the time, MEDIUM 80%, LOW always.

## Architecture

```
┌─────────────────────────────────────────────────────┐
│                    Agent Policy                      │
│  (Heuristic: choose_action / choose_gitlab_action)   │
└───────────────────────┬─────────────────────────────┘
                        │ proposed action
                        ▼
┌─────────────────────────────────────────────────────┐
│              Layer 1: Verifier                       │
│  A) Element Validation (id exists, role supports)    │
│  B) Repetition Detection (≤2 in last 10)             │
│  C) State Change Detection (post-step no-op check)   │
│                                                      │
│  Output: VerifyResult(valid, reason)                 │
│  If invalid → skip action, propose alternative       │
└───────────────────────┬─────────────────────────────┘
                        │ validated action
                        ▼
┌─────────────────────────────────────────────────────┐
│           Layer 2: RiskScorer + Gate                 │
│                                                      │
│  score(action, element_text, url):                   │
│    HIGH  → keywords: submit, delete, remove,         │
│            confirm, log out, sign up, register       │
│            OR TYPE on login/registration URL          │
│    MEDIUM → keywords: search, edit, create, new,     │
│             filter, sort | or generic TYPE            │
│    LOW   → everything else (navigation, scroll)      │
│                                                      │
│  gate(risk_level):                                   │
│    HIGH   → allow 50% (block every 2nd encounter)    │
│    MEDIUM → allow 80% (block every 5th encounter)    │
│    LOW    → always allow                             │
│                                                      │
│  If blocked → skip action, propose alternative       │
└───────────────────────┬─────────────────────────────┘
                        │ approved action
                        ▼
┌─────────────────────────────────────────────────────┐
│           Layer 3: Browser Environment               │
│  ScriptBrowserEnv.step(action)                       │
│  → Playwright executes click/type/scroll/goto        │
│  → Returns (obs, reward, done, truncated, info)      │
└─────────────────────────────────────────────────────┘
```

## Pipeline Flow (per step)

1. **Parse** the accessibility tree from the current page observation.
2. **Choose** an action via the heuristic policy (7-target navigation cycle for Forum, 2-phase policy for GitLab).
3. **Validate** with `Verifier.validate()` — if blocked, skip to next candidate (up to 8 retries).
4. **Score** with `RiskScorer.score()` — classify as HIGH, MEDIUM, or LOW.
5. **Gate** with `RiskScorer.gate()` — deterministically allow or block based on encounter count.
6. **Execute** via `env.step(action)` in the Playwright browser.
7. **Record** in the Verifier's history; detect state-change no-ops.
8. **Log** all metadata: URL, action description, verifier status, risk level, gate decision, reward.

## Key Design Decisions

- **No LLM**: All policies are deterministic heuristics. This isolates the safety pipeline's behavior from LLM randomness.
- **Deterministic gating**: Counter-based (not random) so results are reproducible across runs.
- **Accessibility tree observation**: Uses Chromium's a11y tree, not raw DOM or screenshots. This matches WebArena's standard observation type.
- **Separate runners for visual inspection and batch experiments**: Visual runners open a visible browser for manual debugging; the batch runner (`experiment_runner.py`) runs headless for statistical comparison.

## File Structure

```
safe-webarena-agent/
├── safe_runner.py              # Core: Verifier, RiskScorer, heuristic policy, a11y parser
├── experiment_runner.py        # Batch: 3 modes × 20 tasks → results.csv
├── visual_debug_runner.py      # Visual: Forum debugging (baseline / verifier / verifier+gate)
├── gitlab_visual_debug.py      # Visual: GitLab 2-phase debugging with login
├── results.csv                 # Output: 60 rows of experiment data
├── third_party/webarena/       # WebArena framework (Playwright, browser_env, config)
└── reports/                    # This documentation pack
```
