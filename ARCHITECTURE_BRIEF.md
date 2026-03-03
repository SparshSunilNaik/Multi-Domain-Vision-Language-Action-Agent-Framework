# Architecture Brief

A 10-minute overview of the VLA Agent Framework for teammates.

---

## System Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                          CLI / DEMO LAYER                               │
│                                                                         │
│   interactive_vla_demo.py          composite_orchestrator_v3.py         │
│   ┌──────────┐ ┌──────────┐       ┌──────────┐ ┌──────────┐           │
│   │--inter-  │ │--full-   │       │--instruc-│ │--full-   │           │
│   │active    │ │demo      │       │tion      │ │eval      │           │
│   └────┬─────┘ └────┬─────┘       └────┬─────┘ └────┬─────┘           │
│        │             │                  │             │                 │
│        └─────────────┼──────────────────┼─────────────┘                 │
│                      ▼                  ▼                               │
│              ┌───────────────────────────────┐                          │
│              │       DOMAIN ROUTER           │                          │
│              │                               │                          │
│              │  CRUD words → Forum/GitLab    │                          │
│              │  YouTube    → Composite       │                          │
│              │  Other      → VLA Agent       │                          │
│              └───────┬───────────────────────┘                          │
└──────────────────────┼──────────────────────────────────────────────────┘
                       │
        ┌──────────────┼──────────────┐
        ▼              ▼              ▼
┌──────────────┐ ┌──────────┐ ┌──────────────┐
│ COMPOSITE    │ │   VLA    │ │   LLM CRUD   │
│ ORCHESTRATOR │ │  AGENT   │ │   ENGINE     │
│              │ │  v1.3    │ │              │
│ Decompose    │ │          │ │ Forum CRUD   │
│ → Execute    │ │ DOM→LLM  │ │ GitLab CRUD  │
│ → Verify     │ │ →Action  │ │              │
│ → Chain      │ │ →Verify  │ │ Login→CRUD   │
│ → HITL       │ │          │ │ →Verify      │
└──────┬───────┘ └────┬─────┘ └──────┬───────┘
       │              │               │
       └──────────────┼───────────────┘
                      ▼
       ┌──────────────────────────────┐
       │      SHARED INFRASTRUCTURE   │
       │                              │
       │  ┌──────────┐ ┌───────────┐  │
       │  │  Ollama   │ │Playwright │  │
       │  │ qwen3:8b  │ │ Chromium  │  │
       │  └──────────┘ └───────────┘  │
       │  ┌──────────┐ ┌───────────┐  │
       │  │  Memory   │ │  Input    │  │
       │  │  Manager  │ │ Grounding │  │
       │  └──────────┘ └───────────┘  │
       └──────────────────────────────┘
```

---

## Data Flow

```
User Instruction
       │
       ▼
┌─────────────┐
│  1. PLAN    │  LLM receives: instruction + URL + DOM elements
│             │  LLM outputs:  ACTION [id] "value" + reasoning
└──────┬──────┘
       │
       ▼
┌─────────────┐
│  2. DOM     │  JavaScript injects data-vla-id on all interactive elements
│  EXTRACT    │  Extracts: tag, type, text, placeholder, href
│             │  Sends element list to LLM as numbered options
└──────┬──────┘
       │
       ▼
┌─────────────┐
│  3. ACTION  │  Playwright executes: click, type, scroll, select
│  EXECUTE    │  Input grounding validates element exists in DOM
│             │  Screenshots captured before/after
└──────┬──────┘
       │
       ▼
┌─────────────┐
│  4. VERIFY  │  Check: URL keyword match? Page text marker?
│             │  Count steps. Compute adherence score.
│             │  If DONE or keyword found → stop
└──────┬──────┘
       │
       ▼
┌─────────────┐
│  5. MEMORY  │  Load memory_store.json
│  ENRICH     │  Auto-fill form fields with stored profile
│             │  Detect which fields were used
└──────┬──────┘
       │
       ▼
┌─────────────┐
│  6. NEXT    │  If composite: pass extracted variables to next step
│  STEP       │  If complete: generate report
│             │  If failed: HITL escalation
└─────────────┘
```

---

## Domain Routing Logic

The router inspects instruction keywords to decide which engine handles the task:

```
Instruction keywords              → Engine
─────────────────────────────────────────────────
forum, post, reply, submission    → Forum CRUD
gitlab, project, issue            → GitLab CRUD
create, edit, delete, crud        → CRUD (default: Forum)
watch, play, youtube, video       → Composite Orchestrator
(everything else)                 → VLA Unified Agent
```

Within the VLA agent, the start URL determines the domain:

```
URL contains                      → Domain
─────────────────────────────────────────────────
en.wikipedia.org                  → Wikipedia
google.com                        → Google
youtube.com                       → YouTube
localhost:8001                    → Store
localhost:8002                    → Booking
localhost:9999                    → Forum
localhost:8023                    → GitLab
```

---

## Composite Chaining Flow

```
"Find who created Python and search that person on Google."
                    │
                    ▼
           ┌───────────────┐
           │  DECOMPOSE    │  LLM breaks into 2 steps:
           │  (LLM call)   │  1. Wikipedia: search Python
           │               │  2. Google: search {{creator}}
           └───────┬───────┘
                   │
        ┌──────────┼──────────┐
        ▼                     ▼
┌──────────────┐      ┌──────────────┐
│ Step 1:      │      │ Step 2:      │
│ Wikipedia    │      │ Google       │
│              │      │              │
│ Search for   │─────►│ Search for   │
│ Python       │  {{creator}}="Guido │
│              │  van Rossum"        │
│ EXTRACT:     │      │              │
│ creator =    │      │ URL matches  │
│ Guido van    │      │ search?q=    │
│ Rossum       │      │ → SUCCESS    │
└──────────────┘      └──────────────┘

Variable Flow:
  Step 1 extracts "creator" → stored in variables dict
  Step 2 substitutes {{creator}} → "Guido van Rossum"
  Verification: extraction validated with name regex
```

---

## HITL Injection Point

HITL activates at three points in the execution pipeline:

```
                    ┌─────────────────┐
                    │   PLAN STEP     │
                    └────────┬────────┘
                             │
                    ┌────────▼────────┐
                    │ Substitute vars │
                    │ + memory        │
                    └────────┬────────┘
                             │
                    ┌────────▼────────┐     ┌──────────────────┐
            ╔═══►  │ Missing {{var}}? │────►│ HITL: Ask user   │
            ║       └────────┬────────┘  Y  │ for variable     │
            ║                │ N            └────────┬─────────┘
            ║       ┌────────▼────────┐              │
            ║       │ EXECUTE STEP    │◄─────────────┘
            ║       └────────┬────────┘
            ║                │
            ║       ┌────────▼────────┐
            ║       │ EXTRACT value   │
            ║       └────────┬────────┘
            ║                │
            ║       ┌────────▼────────┐     ┌──────────────────┐
  HITL ═════╬═══►  │ Validate + retry│────►│ HITL: Ask user   │
  Points    ║       │ Failed?         │  Y  │ for correct value│
            ║       └────────┬────────┘     └────────┬─────────┘
            ║                │ N                     │
            ║       ┌────────▼────────┐              │
            ║       │ CHECK success   │◄─────────────┘
            ║       └────────┬────────┘
            ║                │
            ║       ┌────────▼────────┐     ┌──────────────────┐
            ╚═══►  │ Step failed?    │────►│ HITL: Ask user   │
                    │                 │  Y  │ for guidance     │
                    └────────┬────────┘     └──────────────────┘
                             │ N
                    ┌────────▼────────┐
                    │ NEXT STEP       │
                    └─────────────────┘
```

**Key design principle**: HITL is _silent_ during normal execution. It only surfaces when the system has exhausted automated recovery (retry + fallback). This minimizes user interruption while preventing silent failures.

---

## Quick Reference

| Component | File | One-liner |
|-----------|------|-----------|
| Core Agent | `vla_unified_agent_v1_3.py` | DOM→LLM→Action loop |
| Composite v3 | `composite_orchestrator_v3.py` | Multi-domain + HITL |
| Demo | `interactive_vla_demo.py` | Unified CLI entry point |
| CRUD | `llm_crud_v1/` | Forum + GitLab CRUD |
| Memory | `memory_manager_v1.py` | Profile persistence |
| Grounding | `input_grounding_v1_3.py` | DOM action validation |
| YouTube | `youtube_playback_extension_v1.py` | Video playback |
