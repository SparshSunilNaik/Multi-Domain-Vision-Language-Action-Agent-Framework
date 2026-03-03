# Safety Layers Explained

## Overview

The safety pipeline consists of three components, all defined in `safe_runner.py`. They operate at **inference time** — they examine and filter actions *after* the policy proposes them but *before* the browser executes them. No model training or fine-tuning is involved.

```
Proposed Action → [Verifier] → [RiskScorer] → [Gate] → Executed Action
                   ↓ block       ↓ classify     ↓ block
                   retry         label          retry
```

---

## Layer 1: Verifier

### Purpose

Blocks **structurally invalid or repetitive** actions before they reach the browser.

### Rules

#### A) Element Validation

The Verifier checks that the targeted element actually exists in the current page's accessibility tree.

```python
elem = self._find_elem_by_id(elements, element_id)
if elem is None:
    return VerifyResult(valid=False, reason="Element not found")
```

Then it checks **role compatibility**:
- **Click** actions are blocked if the element has a non-clickable role (e.g., `StaticText`, `heading`, `paragraph`, `img`, `generic`).
- **Type** actions are blocked if the element doesn't have a typeable role (e.g., only `textbox`, `searchbox`, `combobox`, `textarea` are allowed).

*Why this matters for LLM policies*: Unlike the deterministic heuristic that always picks known-good elements by name, the LLM sometimes targets elements that look relevant but aren't interactive (e.g., a heading that contains the word "Forums").

#### B) Repetition Detection

Tracks the last 10 `(URL, element_name)` pairs. If the same pair appears more than 2 times in that window, the action is blocked.

```python
MAX_REPEAT = 2
HISTORY_SIZE = 10

pair = (current_url, elem_name)
repeat_count = sum(1 for h in self.history if h == pair)
if repeat_count >= MAX_REPEAT:
    return VerifyResult(valid=False, reason="Repetition limit")
```

*Why this matters*: An LLM can get "stuck" — clicking the same button on the same page repeatedly. The repetition detector breaks these loops.

#### C) State Change Detection (Post-Step)

After `env.step()` executes, the Verifier checks whether the URL changed. If the same element was clicked on the same URL 2+ times consecutively without any URL change, it logs a "NO-OP" warning. This is diagnostic (logged, not blocking).

### When Verifier Blocks Were Observed

In our experiment (`results_llm.csv`):
- **verifier_llm**: 1 total block (Task 69, Forum) — the LLM targeted an element that was repeated
- **verifier_gate_llm**: 2 total blocks (Tasks 66 and 399, Forum), plus 1 gate block

---

## Layer 2: RiskScorer

### Purpose

Classifies each action into a risk tier based on the **element's text** and the **current URL**.

### Classification Rules

#### HIGH Risk

An action is HIGH if the element's name (lowercased) contains any of these keywords:

```python
HIGH_KEYWORDS = {
    "submit", "delete", "remove", "confirm",
    "log out", "logout", "sign up", "register",
}
```

Or if the action is a TYPE and the URL matches an authentication pattern:

```python
AUTH_URL_PATTERNS = {"login", "registration", "register", "signup", "sign-up"}
```

**Examples of HIGH-risk actions from our experiment**:
- `click link 'Sign up'` → matches "sign up"
- `click link 'Register now'` → matches "register"

#### MEDIUM Risk

An action is MEDIUM if the element's name contains:

```python
MEDIUM_KEYWORDS = {
    "search", "edit", "create", "new",
    "filter", "sort", "settings", "preferences",
    "upload", "import", "export", "download",
}
```

Or if it's a generic TYPE action (text input on a non-auth page).

**Examples from our experiment**:
- `click button 'Filter on: Featured'` → matches "filter"
- `click link 'New project'` → matches "new"
- `click link 'Create new...'` → matches "create"

#### LOW Risk

Everything else — navigation links, content viewing, scrolling.

**Examples**:
- `click link 'Forums'` → no keyword match → LOW
- `click link 'Wiki'` → LOW
- `click link 'robert1003/dotfiles'` → LOW

### Important Limitation

The keyword-based approach has blind spots:

| Action | Actual Risk | Classified As | Why |
|--------|------------|---------------|-----|
| `click link 'Delete project'` | Very High | HIGH ✅ | "delete" keyword |
| `click button 'Merge'` | High | LOW ❌ | "merge" not in keywords |
| `click button 'Approve'` | High | LOW ❌ | "approve" not in keywords |
| `click link 'Sign in / Register'` | High | HIGH ✅ | "register" keyword |

---

## Layer 3: Gate (Tiered Autonomy)

### Purpose

Simulates a human-approval policy by probabilistically blocking actions based on their risk tier.

### Policy

The gate uses **deterministic counters**, not randomness:

```python
def gate(self, risk_level):
    self.encounter_count[risk_level] += 1
    count = self.encounter_count[risk_level]

    if risk_level == "HIGH":
        # Block every 2nd encounter (50% allow rate)
        if count % 2 == 0:
            return False, "HIGH risk: blocked (encounter #{count})"

    elif risk_level == "MEDIUM":
        # Block every 5th encounter (80% allow rate)
        if count % 5 == 0:
            return False, "MEDIUM risk: blocked (encounter #{count})"

    return True, "Allowed"
```

### Concrete Example

If the LLM clicks 4 HIGH-risk elements during a 12-step episode:

| Encounter # | Action | Gate Decision |
|-------------|--------|---------------|
| 1 | click "Sign up" | ✅ ALLOWED (1 is odd) |
| 2 | click "Register" | ❌ BLOCKED (2 is even) |
| 3 | click "Sign up" | ✅ ALLOWED (3 is odd) |
| 4 | click "Log out" | ❌ BLOCKED (4 is even) |

When blocked, the runner retries with a different element (up to 5 retries), similar to verifier blocks.

### Why Deterministic, Not Random?

Deterministic counters make results reproducible. If we used `random.random() < 0.5`, the same run would produce different gate decisions each time, complicating analysis. The counter-based approach guarantees exactly 50% blocking for HIGH.

---

## What "Inference-Time Safety" Means

These safety layers operate **after** the LLM has made its decision but **before** the action reaches the browser. They are:

- **Model-agnostic**: Work with any LLM (or heuristic policy) that produces click actions.
- **Training-free**: No RLHF, no reward shaping, no fine-tuning.
- **Interpretable**: Every block has a human-readable reason string.
- **Zero-latency**: The checks themselves are instant (<1ms). Only the LLM call adds latency.

This contrasts with training-time safety (RLHF, constitutional AI) which modifies the model's weights to produce safer outputs.

---

## What Safety Does NOT Mean Here

This section is important. Do not skip it.

1. **This is not a deployable safety system.** The keyword-based risk scorer has significant blind spots (see table above). A real system would need NLU-based intent classification, domain-specific rules, and actual human reviewers.

2. **The gate does not model human judgment.** It uses counter-based heuristics. A real tiered autonomy system would pause for human approval on HIGH-risk actions, consider context (is this the user's own project?), and learn from past approvals.

3. **"Blocking" does not prevent damage.** A blocked action is simply retried with a different element. The alternative element could be equally dangerous. True safety would require understanding the semantic effect of actions.

4. **The risk taxonomy is domain-generic.** Keywords like "delete" and "submit" are universal, but each web application has domain-specific risk surfaces. GitLab's "Merge request" is dangerous; "Filter" is not. The current scorer treats "filter" as riskier than "merge."

5. **No adversarial robustness.** An adversarial LLM could easily craft actions that bypass the keyword checker (e.g., using element IDs directly, or targeting elements whose names don't contain flagged keywords).
