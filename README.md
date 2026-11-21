# Vision-Language-Action Agent Framework

A multi-domain, LLM-driven web automation framework that converts natural language instructions into executable browser actions. Built on Playwright for browser control and Ollama (qwen3:8b) for on-device LLM inference, the system supports authenticated CRUD operations, cross-domain task chaining, memory persistence, and Human-in-the-Loop (HITL) escalation.

**Project page:** [sparshsunilnaik.github.io/Multi-Domain-Vision-Language-Action-Agent-Framework](https://sparshsunilnaik.github.io/Multi-Domain-Vision-Language-Action-Agent-Framework/), with an interactive replay of the agent loop, the router and safety rules running live, and results from the evaluation reports. The site lives in `docs/`.

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                     USER / CLI / DEMO INTERFACE                     │
│         interactive_vla_demo.py  │  composite_orchestrator_v3.py    │
├─────────────────────────────────────────────────────────────────────┤
│                      ORCHESTRATION LAYER                            │
│  ┌─────────────┐  ┌──────────────┐  ┌────────────────────────────┐ │
│  │  Composite   │  │   Domain     │  │  HITL Escalation Engine   │ │
│  │  Decomposer  │  │   Router     │  │  (missing var / failed    │ │
│  │  (LLM plan)  │  │              │  │   extraction / step fail) │ │
│  └──────┬───────┘  └──────┬───────┘  └────────────┬───────────────┘ │
├─────────┼─────────────────┼────────────────────────┼────────────────┤
│         ▼                 ▼                        ▼                │
│  ┌─────────────────────────────────────────────────────────────────┐ │
│  │                   VLA UNIFIED AGENT (v1.3)                     │ │
│  │  Instruction → DOM Extraction → LLM Plan → Action → Verify    │ │
│  └────┬────────────────┬──────────────────┬───────────────────────┘ │
├───────┼────────────────┼──────────────────┼─────────────────────────┤
│       ▼                ▼                  ▼                         │
│  ┌──────────┐   ┌────────────┐   ┌──────────────────┐              │
│  │   LLM    │   │    DOM     │   │  Action Executor  │              │
│  │  Ollama  │   │ Extraction │   │   (Playwright)    │              │
│  │ qwen3:8b │   │ data-vla-id│   │ click/type/scroll │              │
│  └──────────┘   └────────────┘   └──────────────────┘              │
├─────────────────────────────────────────────────────────────────────┤
│                        SUPPORT LAYERS                               │
│  ┌────────────┐  ┌───────────────┐  ┌─────────────────────────────┐ │
│  │  Memory    │  │  Extraction   │  │  CRUD Engines               │ │
│  │  Manager   │  │  Verifier +   │  │  Forum (Postmill)           │ │
│  │  (JSON)    │  │  Retry Logic  │  │  GitLab                     │ │
│  └────────────┘  └───────────────┘  └─────────────────────────────┘ │
├─────────────────────────────────────────────────────────────────────┤
│                    LOCAL ADVERSARIAL DOMAINS                         │
│           Store (port 8001)  │  Booking (port 8002)                 │
│           Forum (port 9999)  │  GitLab  (port 8023)                 │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Supported Domains

| Domain | URL | Capabilities |
|--------|-----|-------------|
| **Wikipedia** | `https://en.wikipedia.org` | Search, navigate, extract facts |
| **Google** | `https://www.google.com` | Search queries |
| **YouTube** | `https://www.youtube.com` | Search + video playback |
| **Store** | `http://localhost:8001` | Product purchase flow |
| **Booking** | `http://localhost:8002` | Hotel reservation flow |
| **Forum (Postmill)** | `http://localhost:9999` | Authenticated CRUD (Create/Edit/Reply/Delete) |
| **GitLab** | `http://localhost:8023` | Authenticated CRUD (Project/Edit/Issue/Delete) |
| **Composite** | Multi-domain | Cross-domain task chaining |

---

## Features

- **PLAN→ACTION Scaffold** — LLM generates structured plans before acting
- **DOM Injection (`data-vla-id`)** — Stable element targeting via injected attributes
- **Memory Persistence** — User profile stored in `memory_store.json`, auto-filled in forms
- **Variable Extraction** — Extract facts from pages and chain across steps
- **Extraction Verification** — Regex validators for year/name/URL types
- **Retry + Fallback** — Single retry with infobox scan → pattern scan → LLM re-extraction
- **HITL Escalation** — Human-in-the-loop when extraction fails or variables are missing
- **Authenticated CRUD** — LLM-driven Login→Create→Edit→Reply/Issue flows
- **Multi-Domain Chaining** — Composite orchestrator decomposes instructions across domains
- **YouTube Playback** — Detects watch intent, searches, and auto-plays videos
- **Input Grounding** — Validates LLM-suggested actions against actual DOM state

---

## CLI Usage

### Unified Agent (single domain)
```bash
.venv/bin/python vla_unified_agent_v1_3.py --instruction "Search for Alan Turing on Wikipedia." \
    --start-url "https://en.wikipedia.org"
```

### Composite Orchestrator V1.1 (cross-domain)
```bash
.venv/bin/python composite_orchestrator_v1_1.py --instruction \
    "Find who created Python and search that person on Google."
```

### Composite V2 (schema-safe + extraction verification)
```bash
.venv/bin/python composite_orchestrator_v2.py --scenarios composite_scenarios_v2.json
```

### Composite V3 (HITL + full eval)
```bash
.venv/bin/python composite_orchestrator_v3.py --full-eval
.venv/bin/python composite_orchestrator_v3.py --instruction "Search for {{mystery_person}} on Google."
```

### Interactive Demo (all domains)
```bash
.venv/bin/python interactive_vla_demo.py --interactive
.venv/bin/python interactive_vla_demo.py --full-demo
```

### LLM CRUD Suite
```bash
.venv/bin/python llm_crud_v1/run_llm_crud_suite.py
```

### Cross-Domain Evaluation
```bash
.venv/bin/python cross_domain_eval_v1_3.py
```

---

## Directory Structure

```
safe-webarena-agent/
│
├── vla_unified_agent_v1_3.py         # Core VLA agent (DOM→LLM→Action loop)
├── vla_unified_agent_v1_2.py         # Prior version (memory integration)
├── vla_unified_agent_v1_1.py         # Prior version (grounding)
├── vla_unified_agent.py              # Original unified agent
│
├── composite_orchestrator_v1.py      # Composite v1 (basic chaining)
├── composite_orchestrator_v1_1.py    # Composite v1.1 (YouTube playback)
├── composite_orchestrator_v1_2.py    # Composite v1.2 (enhanced decomposition)
├── composite_orchestrator_v2.py      # Composite v2 (schema-safe, extraction verify)
├── composite_orchestrator_v3.py      # Composite v3 (HITL + full eval suite)
│
├── interactive_vla_demo.py           # Unified demo entry point (--interactive / --full-demo)
│
├── memory_manager_v1.py              # Memory CRUD + regex extraction
├── memory_store.json                 # Persistent user profile data
│
├── input_grounding_v1_3.py           # Input grounding / DOM validation
├── wikipedia_support.py              # Wikipedia-specific helpers
├── youtube_playback_extension_v1.py  # YouTube playback detection + execution
├── type_support.py                   # Typing/input support utilities
│
├── cross_domain_eval_v1_3.py         # Cross-domain evaluation runner
├── cross_domain_scenarios_v1_3.json  # Cross-domain test scenarios
│
├── composite_scenarios_v1.json       # Composite v1 scenario definitions
├── composite_scenarios_v2.json       # Composite v2 scenario definitions
│
├── experiment_runner.py              # Phase 1 experiment runner (rule-based)
├── experiment_runner_llm.py          # Phase 2 experiment runner (LLM)
├── experiment_runner_llm_phase2.py   # Phase 2 refinement
├── experiment_runner_llm_phase3.py   # Phase 3 (action verification)
├── experiment_runner_llm_phase3b.py  # Phase 3b (relaxed verification)
│
├── llm_policy.py                     # LLM policy v1
├── llm_policy_phase2.py              # LLM policy phase 2
├── llm_policy_phase3.py              # LLM policy phase 3
├── llm_policy_phase3b.py             # LLM policy phase 3b
│
├── llm_crud_v1/                      # LLM-driven CRUD operations
│   ├── forum_crud_llm.py             # Forum CRUD (Postmill)
│   ├── gitlab_crud_llm.py            # GitLab CRUD
│   ├── llm_dom_agent.py              # DOM agent for CRUD
│   ├── run_llm_crud_suite.py         # CRUD evaluation suite
│   ├── reports/                      # CRUD reports
│   └── runs/                         # CRUD run traces
│
├── auth_domain_crud_v1/              # Authenticated domain CRUD (earlier version)
│   ├── forum_crud_agent.py
│   ├── gitlab_crud_agent.py
│   ├── crud_runner.py
│   └── crud_scenarios.json
│
├── reports_*/                        # Per-version evaluation reports
│   ├── reports_unified_v1_3/
│   ├── reports_cross_domain_v1_3/
│   ├── reports_composite_v1/
│   ├── reports_composite_v2/
│   ├── reports_composite_v3/
│   ├── reports_memory_v1/
│   └── reports_youtube_playback_v1/
│
├── runs/                             # Per-run execution traces + screenshots
│
├── third_party/webarena/             # WebArena benchmark reference code
│
├── README.md                         # This file
├── SYSTEM_OVERVIEW_REPORT.md         # Technical system overview
└── ARCHITECTURE_BRIEF.md             # Architecture brief for teammates
```

---

## Requirements

| Dependency | Version | Purpose |
|-----------|---------|---------|
| Python | 3.10+ | Runtime |
| Ollama | Latest | Local LLM inference (qwen3:8b) |
| Playwright | Latest | Browser automation |

### Ports Used

| Port | Service |
|------|---------|
| 8001 | Local Store (adversarial web app) |
| 8002 | Local Booking (adversarial web app) |
| 8023 | GitLab (self-hosted) |
| 9999 | Postmill Forum (self-hosted) |
| 11434 | Ollama API |

---

## Setup Instructions

### 1. Clone and create virtual environment
```bash
cd safe-webarena-agent
python3 -m venv .venv
source .venv/bin/activate
```

### 2. Install dependencies
```bash
pip install playwright
playwright install chromium
pip install requests
```

### 3. Start Ollama
```bash
ollama serve
ollama pull qwen3:8b
```

### 4. Start local services
```bash
# Store (port 8001)
cd local_store_v2 && python -m http.server 8001

# Booking (port 8002)
cd local_booking_v2 && python -m http.server 8002

# Forum and GitLab should already be running on their respective ports
```

### 5. Verify setup
```bash
# Check Ollama
curl http://localhost:11434/api/tags

# Check local services
curl -s http://localhost:8001/index.html | head -5
curl -s http://localhost:8002/step1_service.html | head -5
```

---

## Demo Instructions

### Quick Demo (3 minutes)
```bash
# Run the interactive demo — shows all domains
.venv/bin/python interactive_vla_demo.py --full-demo
```

### Comprehensive Evaluation (10 minutes)
```bash
# Full 10-domain eval with HITL scenarios
.venv/bin/python composite_orchestrator_v3.py --full-eval
```

### Interactive Session
```bash
# Free-form instruction mode
.venv/bin/python interactive_vla_demo.py --interactive
# Try: "Search for Alan Turing on Wikipedia."
# Try: "Create a new post on the forum."
# Try: "Buy one notebook."
```

### CRUD Suite Only
```bash
.venv/bin/python llm_crud_v1/run_llm_crud_suite.py
```

---

## Credentials

| Service | Username | Password |
|---------|----------|----------|
| Forum (Postmill) | `MarvelsGrantMan136` | `test1234` |
| GitLab | `root` | `Kite$7v_Mango!Q2-Quartz` |

---

## Reports

All runs generate structured reports in `reports_*/` directories and `runs/` with:
- JSON result summaries
- Markdown reports with tables
- Screenshots (when `visual=True`)
- Execution traces with per-step timing
