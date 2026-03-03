# LLM Policy Explained

## Overview

`llm_policy.py` implements a stochastic web navigation policy using a local LLM (Ollama `qwen3:8b`). It has four functions that form a clean pipeline:

```
build_prompt() → query_ollama() → parse_action() → choose_action()
```

The caller (`experiment_runner_llm.py`) invokes `choose_action()`, which orchestrates the other three.

---

## 1. `build_prompt(task_instruction, current_url, clickable_elements)`

### What It Does

Constructs a minimal, structured prompt that gives the LLM exactly the information it needs to choose one click action.

### The Actual Prompt Template

Given a task instruction `"Tell me the count of comments..."`, URL `http://localhost:9999/forums`, and 3 clickable elements, the prompt looks exactly like this:

```
You are a web navigation agent.

Task:
"Tell me the count of comments that have received more downvotes than upvotes"

Current URL:
http://localhost:9999/forums

Available actions:
1. click link "Forums"
2. click button "Sign up"
3. click link "Log in"

Choose exactly one action in this format:

click <number>

Only output the action.
Do not explain.
```

### Why This Design?

- **Numbered list**: Reduces the LLM's output to a single integer, minimizing parse failures.
- **Explicit format instruction**: "click \<number\>" is unambiguous and easy to regex-match.
- **"Do not explain"**: Prevents the LLM from generating reasoning text before the action (which would waste tokens and complicate parsing).
- **Task instruction included**: Even though the heuristic policy ignores the task, the LLM uses it to make contextually relevant choices (e.g., clicking "Comments" when the task mentions comments).

---

## 2. `query_ollama(prompt)`

### What It Does

Sends an HTTP POST to the local Ollama server and returns the raw response text.

### Request Body

```json
{
  "model": "qwen3:8b",
  "prompt": "<the prompt>",
  "stream": false,
  "options": {
    "temperature": 0.7,
    "num_predict": 20
  }
}
```

### Why `temperature = 0.7`?

- **0.0** would be deterministic (greedy decoding) — defeats the purpose of a stochastic policy.
- **1.0** would be highly random — too many incoherent outputs.
- **0.7** is a common middle ground that produces diverse but sensible choices. The LLM will sometimes pick "Forums" and sometimes "Sign up" for the same page, creating the stochastic variation needed for statistical analysis.

### Why `num_predict = 20`?

The expected output is just `click 3` (7 characters). We set 20 tokens to allow for minor variations (e.g., `click 12`, `Click 1`, or even `I'll click 5`), but not so many that the LLM writes a paragraph. This keeps inference fast (~1-5 seconds) and reduces output noise.

### Error Handling

If the Ollama server is unreachable, times out (60s), or returns invalid JSON, the function returns `"ERROR: <message>"`. The caller's `parse_action()` will then trigger the random fallback.

### Implementation Detail

Uses Python's built-in `urllib.request` (no external HTTP library needed). The `stream: false` setting means the entire response is returned in a single JSON payload, not streamed token-by-token.

---

## 3. `parse_action(response_text, clickable_elements)`

### What It Does

Extracts the action number from the LLM's response and maps it to an element ID.

### Parsing Logic

```python
match = re.search(r"click\s+(\d+)", response_text, re.IGNORECASE)
```

This regex:
- Is case-insensitive (`Click`, `CLICK`, `click` all match)
- Allows whitespace between "click" and the number
- Extracts the first integer after "click"

### Validation

```python
if 1 <= idx <= len(clickable_elements):
    # Valid — return the element at position idx-1
```

The index must be within the range of available elements (1-indexed, as presented in the prompt).

### Hardening Against LLM Output Noise

The LLM sometimes produces unexpected output. Here's how each case is handled:

| LLM Output | Parsed? | Result |
|-------------|---------|--------|
| `click 3` | ✅ Yes | Element #3 |
| `Click 1` | ✅ Yes | Element #1 (case-insensitive) |
| `I think I should click 5` | ✅ Yes | Element #5 (regex finds "click 5" anywhere) |
| `click 99` (out of range) | ❌ No | Random fallback |
| `I'm not sure what to do` | ❌ No | Random fallback |
| `ERROR: Connection refused` | ❌ No | Random fallback |
| `<empty string>` | ❌ No | Random fallback |

### Fallback Behavior

When parsing fails, a random clickable element is chosen:

```python
el = random.choice(clickable_elements)
```

The returned dict includes `"parsed": False` so the caller can track parse success rates.

### Return Value

```python
{
    "action": "click",
    "element_id": "74",           # from the a11y tree
    "element_name": "Forums",     # for logging
    "element_role": "link",       # for logging
    "choice_idx": 1,              # which number the LLM chose (or -1 for fallback)
    "parsed": True,               # whether the LLM output was successfully parsed
}
```

---

## 4. `choose_action(task_instruction, current_url, clickable_elements)`

### What It Does

The top-level function that ties everything together.

```python
def choose_action(task_instruction, current_url, clickable_elements):
    prompt = build_prompt(task_instruction, current_url, clickable_elements)
    t0 = time.time()
    raw = query_ollama(prompt)
    latency = time.time() - t0
    result = parse_action(raw, clickable_elements)
    result["llm_raw"] = raw.strip()[:80]   # truncated for logging
    result["latency"] = latency
    return result
```

### What The Caller Gets

A single dict with:
- The chosen action (`element_id`)
- Inference timing (`latency`)
- The raw LLM output (`llm_raw`, truncated to 80 chars)
- Whether parsing succeeded (`parsed`)

The caller (`experiment_runner_llm.py`) then converts this to a Playwright click action via `create_click_action(element_id=...)` and routes it through the safety layers.

---

## Design Tradeoffs

| Decision | Alternative | Why We Chose This |
|----------|-------------|-------------------|
| Click-only actions | Click + Type + Scroll | Simpler parsing, fewer failure modes. Type actions require additional text generation. |
| Numbered list in prompt | Element IDs directly | Numbers are shorter and easier for the LLM to output. Element IDs are long strings. |
| Random fallback | Retry with different prompt | Retrying costs another 2-5s of latency. Random fallback is instant and keeps the experiment moving. |
| `urllib.request` | `requests` library | Zero additional dependencies. |
| Single prompt (no history) | Multi-turn conversation | Keeps prompt small, reduces latency. The LLM doesn't remember previous actions. |
