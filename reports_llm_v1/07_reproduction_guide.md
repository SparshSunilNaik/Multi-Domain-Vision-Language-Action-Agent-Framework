# Reproduction Guide

## Prerequisites

- **macOS Apple Silicon** (M1/M2/M3/M4), ≥16 GB RAM
- **Docker Desktop** with Rosetta enabled (for GitLab amd64 emulation)
- **Python 3.10+** with venv
- **Ollama** installed and running (`brew install ollama` or from https://ollama.ai)
- **~15 GB disk** for Docker images + model weights

---

## Step 1: Start Docker Containers

```bash
# Start Docker Desktop (if not running)
open -a Docker

# Start Forum container
docker start forum 2>/dev/null || \
  docker run -d --name forum -p 9999:80 postmill-populated-exposed-withcookies

# Start GitLab container
docker start gitlab 2>/dev/null || \
  docker run -d --name gitlab -p 8023:8023 --platform linux/amd64 gitlab-populated-final-port8023
```

## Step 2: Verify Ports

```bash
# Forum — should return 200
curl -s -o /dev/null -w "%{http_code}" http://localhost:9999/
# Expected: 200

# GitLab — may take 3-5 minutes to start, keep retrying
curl -s -o /dev/null -w "%{http_code}" http://localhost:8023/users/sign_in
# Expected: 200
```

## Step 3: Verify Ollama + Model

```bash
# Check Ollama is running
curl -s http://localhost:11434/api/tags | python3 -c "import sys,json; print([m['name'] for m in json.load(sys.stdin)['models']])"
# Expected: ['qwen3:8b'] (or includes 'qwen3:8b')

# If model not present:
ollama pull qwen3:8b

# Quick test — should return a response in ~2s
curl -s http://localhost:11434/api/generate \
  -d '{"model":"qwen3:8b","prompt":"Say hello","stream":false,"options":{"num_predict":5}}' \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['response'])"
```

## Step 4: Python Environment

```bash
cd safe-webarena-agent
source .venv/bin/activate

# Verify imports work
python -c "import safe_runner; print('safe_runner OK')"
python -c "from llm_policy import choose_action; print('llm_policy OK')"
python -c "from browser_env import ScriptBrowserEnv; print('browser_env OK')"
```

## Step 5: Quick Smoke Test (1 task, 5 steps)

The experiment runner includes a built-in validation pass. But if you want to test just the LLM policy in isolation:

```bash
python -c "
from llm_policy import choose_action
elements = [
    {'id': '1', 'role': 'link', 'name': 'Forums'},
    {'id': '2', 'role': 'button', 'name': 'Sign up'},
    {'id': '3', 'role': 'link', 'name': 'Wiki'},
]
result = choose_action('Find comments', 'http://localhost:9999/', elements)
print(f'Chose: {result[\"element_name\"]} (parsed={result[\"parsed\"]}, latency={result[\"latency\"]:.2f}s)')
print(f'LLM raw: {result[\"llm_raw\"]}')
"
```

Expected output (will vary due to stochasticity):
```
Chose: Forums (parsed=True, latency=1.83s)
LLM raw: click 1
```

## Step 6: Run Full Experiment

```bash
cd safe-webarena-agent
source .venv/bin/activate
python experiment_runner_llm.py 2>&1 | tee reports_llm_v1/logs/experiment_run.out
```

**Expected runtime**: 40–60 minutes (3 modes × 15 tasks × ~40-60s per task).

**What you'll see**:
1. Validation pass (1 Forum + 1 GitLab task, 5 steps each, verbose)
2. Mode 1: baseline_llm (15 tasks)
3. Mode 2: verifier_llm (15 tasks)
4. Mode 3: verifier_gate_llm (15 tasks)
5. CSV saved to `results_llm.csv`
6. Aggregate summary table

**Browser visibility**: The browser runs with `headless=False`, so you'll see Chromium navigating pages in real-time.

## Step 7: Verify Output

```bash
# Check CSV was created
wc -l results_llm.csv
# Expected: 46 (1 header + 45 data rows)

# Quick stats
python -c "
import csv
with open('results_llm.csv') as f:
    rows = list(csv.DictReader(f))
print(f'Rows: {len(rows)}')
print(f'Modes: {set(r[\"mode\"] for r in rows)}')
print(f'Domains: {set(r[\"domain\"] for r in rows)}')
"
```

---

## Troubleshooting

### Docker containers not healthy

**Symptom**: `curl` to port 9999 or 8023 returns connection refused.

**Fix**:
```bash
# Check container status
docker ps -a --format '{{.Names}} {{.Status}}'

# If container is "Exited", restart it
docker start forum
docker start gitlab

# If container doesn't exist, re-create from image
docker run -d --name forum -p 9999:80 postmill-populated-exposed-withcookies
```

**GitLab-specific**: GitLab takes 3-5 minutes to fully start. Check logs:
```bash
docker logs gitlab --tail 20
```
Wait until you see `"gitlab Reconfigured!"` or the HTTP endpoint responds.

### Ollama not responding

**Symptom**: `experiment_runner_llm.py` hangs or returns `ERROR: Connection refused`.

**Fix**:
```bash
# Check if Ollama is running
pgrep -f ollama

# Start Ollama server
ollama serve &

# Verify
curl -s http://localhost:11434/api/tags
```

**If model not loaded**:
```bash
ollama pull qwen3:8b
# This downloads ~5GB; wait for completion
```

### Playwright issues

**Symptom**: `Error: Browser closed unexpectedly` or `Timeout`.

**Fix**:
```bash
# Reinstall browser binaries
python -m playwright install chromium

# Check if another Chromium process is blocking
pkill -f chromium
```

### Slow runs (>90 minutes)

**Possible causes**:
1. **Ollama is CPU-only**: If no GPU is available, inference is slow. Check with `ollama ps`.
2. **Docker resource contention**: GitLab under amd64 emulation uses 4-6GB RAM. Close other apps.
3. **Network latency**: Ollama runs on `localhost:11434`. If routed through Docker networking, this adds latency.

**Mitigation**: Reduce task count temporarily:
```python
# In experiment_runner_llm.py:
NUM_FORUM_TASKS = 5   # was 10
NUM_GITLAB_TASKS = 2  # was 5
```

### Results differ from reported values

**This is expected.** The LLM policy is stochastic (temperature=0.7). Each run produces different actions and therefore different metrics. The aggregate trends (baseline has 0 blocks, verifier mode has some) should hold, but exact numbers will vary.
