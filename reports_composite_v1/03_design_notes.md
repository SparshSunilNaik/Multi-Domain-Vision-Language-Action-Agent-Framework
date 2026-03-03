# Design Notes — Composite Orchestrator v1

## Why Planning + Extraction + Variable Passing?

### Problem
Single-domain agents can execute tasks within one website, but real-world user
instructions often span multiple domains. "Find X on Wikipedia, then search for it
on Google" requires:
1. Navigating to Wikipedia and finding X
2. **Extracting** the fact (X) from the page
3. **Carrying** that fact to a new domain
4. Using it in the next instruction

### Solution: Composite Orchestrator

```
User: "Find Turing's birth year on Wikipedia, search Google for events that year"
                    ↓
            ┌─── PLAN ───┐
            │ Step 1: Wiki│── extract birth_year → {1912}
            │ Step 2: Ggl │── substitute {{birth_year}}
            └─────────────┘
                    ↓
        "Search Google for 'events in 1912'"
```

### Key Design Decisions

1. **Pre-built plans for known scenarios** — JSON file with step definitions,
   no LLM needed for decomposition = deterministic & fast.

2. **LLM decomposition for interactive mode** — when the user provides a
   free-form composite instruction, the LLM generates a plan JSON.

3. **Two extraction methods**:
   - **Regex**: fast, deterministic, works for structured data (dates, years)
   - **LLM**: flexible, handles natural language extraction (person names)

4. **Variable substitution** via `{{var_name}}` — simple, transparent,
   debuggable. Variables are logged in the trace.

5. **Early stopping** — if the final completion keyword is matched before
   all steps execute, stop immediately to save tokens.

6. **Same browser context** — all steps share one Playwright browser context
   but use separate pages, preserving cookies and state.

### Architecture

```
composite_orchestrator_v1.py
├── Import vla_unified_agent_v1_3 (reuse core agent)
├── Variable substitution engine
├── Fact extraction (regex + LLM)
├── LLM plan decomposition (interactive)
├── Sequential step executor
├── Report generator
└── CSV/JSON output
```

### Limitations & Future Work

- Plans are currently linear (step 1 → 2 → ... → N). No branching or parallelism.
- Extraction relies on page text at completion time. If the relevant fact is
  not in the first 2000 chars of body text, extraction may miss it.
- LLM extraction is non-deterministic. The `default` field provides a fallback.
- Variable substitution is literal string replacement. No computed expressions.
