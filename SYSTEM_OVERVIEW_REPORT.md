# System Overview Report

## 1. Evolution Timeline

The system evolved through 10 distinct phases, each adding a capability layer:

```
Phase 1 ─────► Phase 2 ─────► Phase 3A ────► Phase 3B
(Rule-based)   (LLM policy)   (Verification)  (Relaxed)
     │              │              │               │
     └──────────────┴──────────────┴───────────────┘
                         │
                    Unified Agent v1.0
                         │
                    v1.1 (Grounding)
                         │
                    v1.2 (Memory)
                         │
                    v1.3 (Cross-Domain)
                         │
              ┌──────────┼──────────┐
              ▼          ▼          ▼
         Composite   LLM CRUD   Memory
         v1 → v1.1   (Forum +   Manager
         → v1.2      GitLab)
         → v2 (schema-safe)
         → v3 (HITL)
              │
          Interactive
          VLA Demo
```

| Phase | Key Addition | File |
|-------|-------------|------|
| Phase 1 | Rule-based action selection | `experiment_runner.py` |
| Phase 2 | LLM-driven policy (Ollama) | `experiment_runner_llm.py` |
| Phase 3A | Action verification layer | `experiment_runner_llm_phase3.py` |
| Phase 3B | Relaxed verification (fewer false negatives) | `experiment_runner_llm_phase3b.py` |
| Unified v1.0 | Single agent for all domains | `vla_unified_agent.py` |
| v1.1 | Input grounding (DOM validation) | `vla_unified_agent_v1_1.py` |
| v1.2 | Memory persistence (auto-fill) | `vla_unified_agent_v1_2.py` |
| v1.3 | Cross-domain eval + Wikipedia support | `vla_unified_agent_v1_3.py` |
| Composite v1→v1.1 | Multi-domain chaining + YouTube playback | `composite_orchestrator_v1_1.py` |
| Composite v2 | Schema-safe StepResult + extraction verify | `composite_orchestrator_v2.py` |
| Composite v3 | HITL + full eval + CRUD integration | `composite_orchestrator_v3.py` |
| LLM CRUD | Authenticated Forum + GitLab CRUD | `llm_crud_v1/` |
| Demo | Unified interactive entry point | `interactive_vla_demo.py` |

---

## 2. Core Components

### DOM Injection (`data-vla-id`)

The agent injects unique `data-vla-id` attributes into all interactive DOM elements via JavaScript. This provides stable element targeting that survives page re-renders and avoids brittle CSS selectors.

```javascript
// Injected at each step:
document.querySelectorAll('a, button, input, select, textarea, [role="button"]')
    .forEach((el, i) => el.setAttribute('data-vla-id', i));
```

The agent sees elements like:
```
[12] <input type="text" placeholder="Search" data-vla-id="12">
[27] <button>Submit</button data-vla-id="27">
```

### LLM Prompt Structure

Each step sends a structured prompt to the LLM:

```
INSTRUCTION: <user goal>
CURRENT URL: <page URL>
PAGE CONTEXT: <extracted text, max 2000 chars>
INTERACTIVE ELEMENTS:
  [0] <a href="/">Home</a>
  [1] <input type="text" placeholder="Search">
  ...
ACTION FORMAT: ACTION [id] "value"
```

The LLM responds with:
- `CLICK [id]` — Click element
- `TYPE [id] "value"` — Type into input
- `SCROLL UP/DOWN` — Scroll page
- `DONE` — Task complete

### Verification Layer

After each LLM action, the system verifies:
1. **Element exists** — The target `data-vla-id` actually exists in DOM
2. **Action type matches** — TYPE actions target input/textarea elements
3. **Completion keyword** — URL or page text matches expected pattern
4. **Adherence score** — Ratio of grounded actions to total actions

### Memory Enrichment

For form-heavy tasks (Store, Booking), the system:
1. Loads `memory_store.json` (name, email, phone, address, etc.)
2. Appends profile data to the instruction as context
3. The LLM uses these values when filling form fields
4. Post-hoc analysis detects which memory values were auto-filled

### HITL Trigger Logic

Human-in-the-Loop activates **only** when automated systems fail:

```
Extraction attempt → Retry → Still failed?
    ├── YES → Ask human for value
    └── NO  → Continue automatically

Missing {{variable}}?
    ├── In memory?     → Substitute
    ├── In variables?  → Substitute
    └── Neither?       → Ask human

Step failed?
    └── Ask human for guidance or "skip"
```

HITL never activates during normal successful execution.

---

## 3. Current System Capabilities

| Capability | Status | Details |
|-----------|--------|---------|
| Single-domain navigation | ✅ Stable | Wikipedia, Google, YouTube, Store, Booking |
| Multi-domain chaining | ✅ Stable | Composite orchestrator chains 2+ domains |
| Fact extraction | ✅ Working | LLM + regex extraction with verification |
| Variable passing | ✅ Working | `{{var}}` substitution across composite steps |
| Memory auto-fill | ✅ Working | Form fields populated from memory_store.json |
| YouTube playback | ✅ Working | Search + auto-play with browser kept open |
| Forum CRUD | ✅ Working | Login → Create → Edit → Reply (LLM-driven) |
| GitLab CRUD | ✅ Working | Login → Create Project → Edit → Issue |
| HITL escalation | ✅ Working | Missing vars, failed extraction, step failure |
| Structured reporting | ✅ Working | JSON + Markdown + CSV reports |
| Interactive demo | ✅ Working | CLI-based multi-domain demo |

---

## 4. Known Limitations

| Limitation | Impact | Mitigation |
|-----------|--------|------------|
| **LLM rate limits** | Ollama may throttle under sustained load | Add delays between steps |
| **Single retry only** | Complex extractions may need multiple attempts | HITL fills the gap |
| **No parallel execution** | Steps run sequentially | By design for dependency chains |
| **DOM size limit** | Pages with 500+ elements may truncate | Element limit + text truncation |
| **Keyword matching** | Completion detection relies on URL/text keywords | May miss dynamic content |
| **No JavaScript SPAs** | Heavy SPA frameworks may not expose DOM cleanly | Works best on server-rendered pages |
| **Model quality** | qwen3:8b may misinterpret complex instructions | Structured prompts reduce errors |

---

## 5. Future Improvements

| Improvement | Priority | Description |
|------------|----------|-------------|
| **Vision integration** | High | Add screenshot-based reasoning alongside DOM |
| **Parallel step execution** | Medium | Run independent composite steps concurrently |
| **Adaptive retry** | Medium | Dynamic retry count based on extraction confidence |
| **Session persistence** | Medium | Keep browser sessions across composite steps |
| **Model upgrade** | Low | Test with larger models (qwen3:14b, llama3) |
| **Safety gating** | Low | Add configurable safety checks before destructive actions |
| **Evaluation harness** | Low | Automated regression testing with expected outcomes |
