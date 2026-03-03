# reports_memory_v1 — Memory Integration Reports

Stores evaluation reports for memory-augmented agent runs.

## Purpose

Tracks how the memory layer (`memory_manager_v1.py`) improves form-filling accuracy. Reports show which fields were auto-filled from `memory_store.json` and whether the agent correctly used stored profile data (name, email, phone, address, etc.).

## Connection to Main System

- Generated during memory-enabled evaluation runs
- Uses `memory_manager_v1.py` for profile loading and enrichment
- Memory data stored in `memory_store.json` at the project root

## How to Execute

Memory integration is enabled by default in `vla_unified_agent_v1_3.py` for form-heavy domains (Store, Booking). Run any evaluation that includes these domains:

```bash
.venv/bin/python run_phase_validation_v1_3.py
.venv/bin/python composite_orchestrator_v3.py --full-eval
```

## Expected Outputs

| File | Contents |
|------|----------|
| `report_*.md` | Report showing auto-fill detections and memory usage |
| `memory_audit.json` | Which memory keys were used per scenario |
