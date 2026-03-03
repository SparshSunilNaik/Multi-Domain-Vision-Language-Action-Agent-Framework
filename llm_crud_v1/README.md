# llm_crud_v1 — LLM-Driven CRUD Operations

Authenticated CRUD evaluation for **Postmill Forum** and **GitLab**, driven entirely by an LLM agent that interprets DOM state and decides actions at each step.

## Components

| File | Purpose |
|------|---------|
| `llm_dom_agent.py` | Core DOM agent — extracts page text, injects `data-vla-id`, queries LLM for actions |
| `forum_crud_llm.py` | Forum CRUD class (Login → Create → Edit → Reply → Delete) |
| `gitlab_crud_llm.py` | GitLab CRUD class (Login → Create Project → Edit → Issue → Delete) |
| `run_llm_crud_suite.py` | Suite runner — launches Playwright, runs both domains, generates summary report |

## Connection to Main System

- Imported by `interactive_vla_demo.py` for the unified demo entry point
- Imported by `composite_orchestrator_v3.py` for the `--full-eval` test suite
- Uses the same Ollama LLM backend (`qwen3:8b`) as the VLA agent
- Shares the `data-vla-id` DOM injection pattern with the unified agent

## How to Execute

```bash
# Run the full CRUD suite (both Forum + GitLab)
cd safe-webarena-agent
.venv/bin/python llm_crud_v1/run_llm_crud_suite.py

# Or run via interactive demo
.venv/bin/python interactive_vla_demo.py --full-demo
```

## Prerequisites

- Forum running on `http://localhost:9999`
- GitLab running on `http://localhost:8023`
- Ollama running with `qwen3:8b`

## Expected Outputs

- Console output with per-operation success/failure
- `reports/` — Markdown + JSON evaluation reports
- `runs/` — Per-run execution traces and screenshots

## Credentials

| Service | Username | Password |
|---------|----------|----------|
| Forum | `MarvelsGrantMan136` | `test1234` |
| GitLab | `root` | `Kite$7v_Mango!Q2-Quartz` |
