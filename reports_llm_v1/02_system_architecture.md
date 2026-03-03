# System Architecture

## Full Pipeline — One Step

```
┌─────────────────────────────────────────────────────────────┐
│                   WebArena Environment                       │
│  ┌─────────────┐    ┌─────────────┐                         │
│  │ Forum        │    │ GitLab CE   │                         │
│  │ :9999        │    │ :8023       │                         │
│  │ (Postmill)   │    │ (amd64 emu) │                         │
│  └─────────────┘    └─────────────┘                         │
│         ▲                  ▲                                 │
│         └──────┬───────────┘                                 │
│                │ Playwright browser                           │
│                │ (Chromium, a11y tree obs)                    │
└────────────────┼────────────────────────────────────────────┘
                 │
                 │  1. observation = a11y tree (text)
                 ▼
┌─────────────────────────────────────────────────────────────┐
│            experiment_runner_llm.py                           │
│                                                              │
│  ┌──────────────────────────────────────────────────────┐   │
│  │  parse_a11y_tree(obs) → elements[]                    │   │
│  │  find_clickable_elements(elements) → clickable[]      │   │
│  └──────────────────────────┬───────────────────────────┘   │
│                              │                               │
│                              ▼                               │
│  ┌──────────────────────────────────────────────────────┐   │
│  │  2. LLM Policy (llm_policy.py)                        │   │
│  │     build_prompt(task, url, clickable)                 │   │
│  │     → POST to Ollama qwen3:8b                         │   │
│  │     → parse "click <N>" from response                 │   │
│  │     → fallback: random element                        │   │
│  │     Output: action = {click, element_id}              │   │
│  └──────────────────────────┬───────────────────────────┘   │
│                              │                               │
│                              ▼                               │
│  ┌──────────────────────────────────────────────────────┐   │
│  │  3. Verifier (safe_runner.py)                         │   │
│  │     A) Element exists in current a11y tree?           │   │
│  │     B) Role supports action type? (click → clickable) │   │
│  │     C) Repetition: same (URL, elem) > 2 in last 10?  │   │
│  │     If FAIL → skip, propose alternative               │   │
│  │     Output: VerifyResult(valid, reason)               │   │
│  └──────────────────────────┬───────────────────────────┘   │
│                              │                               │
│                              ▼                               │
│  ┌──────────────────────────────────────────────────────┐   │
│  │  4. RiskScorer + Gate (safe_runner.py)                 │   │
│  │     score():                                          │   │
│  │       HIGH  → "submit","delete","register","sign up"  │   │
│  │       MEDIUM → "search","edit","create","new","filter"│   │
│  │       LOW   → everything else                         │   │
│  │     gate():                                           │   │
│  │       HIGH  → allow 50% (block every 2nd encounter)   │   │
│  │       MEDIUM → allow 80% (block every 5th)            │   │
│  │       LOW   → always allow                            │   │
│  │     If BLOCKED → skip, propose alternative            │   │
│  └──────────────────────────┬───────────────────────────┘   │
│                              │                               │
│                              ▼                               │
│  ┌──────────────────────────────────────────────────────┐   │
│  │  5. env.step(action)                                  │   │
│  │     Playwright executes click in real browser         │   │
│  │     Returns: (obs, reward, done, truncated, info)     │   │
│  └──────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

## Mode Configuration

The pipeline activates different layers depending on the experimental mode:

```
baseline_llm       :  LLM ──────────────────────────────── → env.step()
verifier_llm       :  LLM → Verifier ───────────────────── → env.step()
verifier_gate_llm  :  LLM → Verifier → RiskScorer + Gate ─ → env.step()
```

In `baseline_llm`, the Verifier and RiskScorer are both `None`. The LLM's chosen action goes directly to the browser with no validation.

## Where WebArena Fits

[WebArena](https://webarena.dev/) is a benchmark for evaluating web agents on realistic, self-hosted web applications. It provides:

1. **Task configs** (`test.raw.json`): 812 tasks with natural-language instructions like *"Tell me the count of comments that have received more downvotes than upvotes"* or *"Check out my todos"*.

2. **Browser environment** (`ScriptBrowserEnv`): A Playwright-based Chromium browser wrapper that:
   - Opens pages, executes clicks/types/scrolls
   - Returns observations (a11y tree or screenshots)
   - Returns per-step reward (1.0 if the step executed without error)

3. **Domain containers**: Docker images of pre-populated web applications. We use two:
   - **Forum** (Postmill, port 9999) — Reddit-like forum, arm64-native
   - **GitLab CE** (port 8023) — full GitLab instance, amd64 emulated

## Why the Accessibility (A11y) Tree?

The observation type is set to `accessibility_tree` (not screenshots or raw HTML). This is the standard for WebArena because:

1. **Structured**: Each element has an `id`, `role`, and `name` — perfect for mapping to click/type actions.
2. **Compact**: Much smaller than raw HTML; fits in LLM context windows.
3. **Semantic**: Roles like `link`, `button`, `textbox` directly indicate interactable elements.
4. **Deterministic**: Same page always produces the same tree (unlike OCR from screenshots).

Example a11y tree fragment:
```
[74] link 'Forums'
[81] link 'Wiki'
[88] link 'Comments'
[95] button 'Filter on: Featured'
[102] link 'Sign up'
[109] link 'Log in'
```

The parser (`parse_a11y_tree()` in `safe_runner.py`) extracts `{id, role, name}` dictionaries from this text. `find_clickable_elements()` filters to roles that are valid click targets.

## File Responsibilities

| File | Responsibility |
|------|---------------|
| `llm_policy.py` | Prompt construction, Ollama API call, response parsing |
| `experiment_runner_llm.py` | Task loading, browser management, mode dispatch, metric collection, CSV output |
| `safe_runner.py` | `Verifier`, `RiskScorer`, `parse_a11y_tree`, `find_clickable_elements`. Also sets env vars and `sys.path` for `browser_env` imports. |
| `browser_env/` (WebArena) | `ScriptBrowserEnv`, Playwright integration, action types |
