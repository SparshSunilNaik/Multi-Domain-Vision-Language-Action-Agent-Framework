# Design Notes — Memory Layer v1.2

## Deterministic Regex Extraction

Memory extraction from instructions uses ONLY regex patterns — no LLM calls.
This ensures:
- **Speed**: No network latency for memory operations
- **Determinism**: Same input always produces same output
- **Transparency**: Every pattern is inspectable and debuggable

### Patterns Used
```
"my name is X"     → name
"my email is Y"    → email
"my phone is P"    → phone
"my address is Z"  → address
"my city is C"     → city
"my zip is Z"      → zip
"my country is N"  → country
```

Regex is case-insensitive and handles:
- "My name is Sparsh" → {name: "Sparsh"}
- "my email is a@b.com and my phone is 123" → {email: "a@b.com", phone: "123"}

## Memory Injection Strategy

Memory is injected at TWO levels:

1. **Decomposition prompt** — The LLM planner sees the user profile when generating
   the step plan. This helps it include relevant details in step instructions.

2. **Step instruction enrichment** — For booking/store domains, the step instruction
   is appended with: "When filling forms, use these personal details: name=X, email=Y..."
   This ensures the v1.3 agent's LLM uses memory values for TYPE actions.

## Why No LLM for Memory Extraction?

1. **Reliability**: LLMs may hallucinate or misparse fields
2. **Speed**: Regex is instant; LLM calls take 3-5 seconds each
3. **Cost**: No tokens consumed for memory operations
4. **Privacy**: Memory data stays local, never sent to LLM
5. **Debuggability**: Regex patterns are transparent and testable

## Auto-Fill Flow

```
User: "Book a doctor appointment for tomorrow"
         ↓
  Load memory: {name: "Sparsh", email: "sparsh@test.com", ...}
         ↓
  Enrich instruction:
    "Book a doctor appointment for tomorrow.
     When filling forms, use: name=Sparsh, email=sparsh@test.com, ..."
         ↓
  v1.3 agent fills form fields using enriched instruction
         ↓
  Trace analysis: detect which fields matched memory values
         ↓
  Log: AUTO-FILL: field=full_name value=Sparsh
       AUTO-FILL: field=email value=sparsh@test.com
```
