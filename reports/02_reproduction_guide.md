# Reproduction Guide

## Prerequisites

- **Hardware**: macOS Apple Silicon (M1/M2/M3/M4), ≥16 GB RAM recommended
- **Software**: Docker Desktop (with Rosetta emulation enabled for amd64 images), Python 3.10+
- **Disk**: ~15 GB for Docker images

## Step 1: Docker Image Loading

The WebArena Docker images are stored locally and loaded from tar files:

```bash
# Forum (Postmill) — arm64-native, ~2 GB
docker load < webareana_images/postmill-populated-exposed-withcookies.tar

# GitLab CE — amd64 (no arm64 image available), ~7 GB
docker load < webareana_images/gitlab-populated-final-port8023.tar
```

## Step 2: Launch Containers

### Forum (Postmill)

```bash
docker run -d \
  --name forum \
  -p 9999:80 \
  postmill-populated-exposed-withcookies
```

### GitLab CE

```bash
docker run -d \
  --name gitlab \
  -p 8023:8023 \
  --platform linux/amd64 \
  gitlab-populated-final-port8023
```

**Important**: GitLab runs under amd64 emulation on Apple Silicon. Initial startup takes 3–5 minutes. Verify readiness:

```bash
# Wait until this returns HTTP 200 or 302:
curl -s -o /dev/null -w "%{http_code}" http://localhost:8023/users/sign_in
```

## Step 3: Ports Used

| Service | Port | URL |
|---------|------|-----|
| Forum (Postmill) | 9999 | http://localhost:9999 |
| GitLab CE | 8023 | http://localhost:8023 |

## Step 4: Python Environment

```bash
cd safe-webarena-agent

# Create virtual environment
python3.10 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r third_party/webarena/requirements.txt
pip install playwright
python -m playwright install chromium
```

## Step 5: Environment Variables

The scripts set environment variables automatically. For reference, the required variables are:

```bash
export REDDIT="http://localhost:9999"
export SHOPPING="http://localhost:9999"     # unused, but required by browser_env
export SHOPPING_ADMIN="http://localhost:9999"
export GITLAB="http://localhost:8023"       # overridden by gitlab_visual_debug.py
export WIKIPEDIA="http://localhost:9999"
export MAP="http://localhost:9999"
export HOMEPAGE="http://localhost:9999"
```

## Step 6: Running Each Script

### Batch Experiment (headless, ~8 minutes)

```bash
python experiment_runner.py
```

Runs 3 modes × 20 tasks = 60 evaluations against the Forum. Writes results to `results.csv`.

### Visual Debug — Forum (visible browser)

```bash
# Baseline (no safety layers)
python visual_debug_runner.py --mode baseline

# Verifier only
python visual_debug_runner.py --mode verifier

# Full pipeline (verifier + gate)
python visual_debug_runner.py --mode verifier+gate
```

Opens a visible Chromium window. 12 steps with 0.8s delay. Prints structured logs to stdout.

### Visual Debug — GitLab (visible browser)

```bash
python gitlab_visual_debug.py
```

Opens a visible Chromium window. 12 steps with 1.0s delay. Two-phase exploration:
- Phase 1 (steps 1–6): Unauthenticated sign-in/sign-up pages (HIGH risk)
- Phase 2 (steps 7–12): Authenticated dashboard after login (MEDIUM/LOW)

## Known Issues

### amd64 Emulation on Apple Silicon

GitLab's Docker image is amd64-only. Under Rosetta/QEMU emulation:
- **Startup is slow**: 3–5 minutes before the web UI responds.
- **CPU usage is high**: GitLab's background jobs (Sidekiq, Puma) consume significant CPU under emulation.
- **RAM**: GitLab alone uses 4–6 GB. With Forum and the browser, total usage is 8–12 GB.

### Browser Viewport

The visible browser window uses 1280×720 viewport. Elements below the fold are not visible in `current_viewport_only=True` mode (the default). This affects which elements the heuristic policy can interact with.

### Pyre2 Lint Warnings

The IDE's Pyre2 type checker reports false positive errors on imports from `safe_runner` and `browser_env` because these modules use dynamic `sys.path` manipulation. These warnings are safe to ignore and do not affect runtime behavior.

### GitLab Session Behavior

When logged into GitLab, navigating to `/users/sign_in` or `/users/sign_up` redirects to the dashboard. The `gitlab_visual_debug.py` script accounts for this by using a two-phase approach: Phase 1 operates while unauthenticated, then Phase 2 logs in at the step boundary.

### GitLab Sign-Out

GitLab's sign-out endpoint (`/users/sign_out`) requires a DELETE HTTP method with CSRF protection. A simple GET request does not terminate the session. The script works around this by structuring phases rather than trying to sign out mid-session.
