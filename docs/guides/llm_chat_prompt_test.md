# LLM Chat Prompt Test

Use this test pack to verify that chat behavior matches the intended architecture:
- small vs large model routing
- LangGraph path selection
- memory write/recall behavior
- tool request behavior

## How to Use

1. Start the app and open a fresh chat thread.
2. Run each prompt in order (some are multi-turn).
3. Compare actual behavior with expected results.
4. Mark each case as pass/fail.

Tip: Keep "show tool execution" enabled in settings so tool calls are visible.

---

## Test 1 - Small Route (Simple Response)

### Prompt
`Hi! Reply with exactly: SMALL_OK`

### Expected
- Fast response (typically low latency).
- Direct answer with no tool request.
- No multi-step reasoning text.
- Output should be exactly `SMALL_OK`.

### Pass Criteria
- Route behaves like `simple`.
- No tool invocation card/event appears.

---

## Test 2 - Large Route (Complex Reasoning)

### Prompt
`Design a 3-phase migration plan from monolith to microservices for a 20-person engineering team, including risks, rollback strategy, and weekly milestones.`

### Expected
- Rich, structured, multi-part response.
- Slower than Test 1 (uses deeper reasoning path).
- No tool needed unless model decides to fetch external context.

### Pass Criteria
- Response quality indicates complex planning.
- Behavior aligns with `complex` route characteristics.

---

## Test 3 - Tool Request Behavior

### Prompt
`Please search the web for "latest LangGraph release highlights" and summarize in 5 bullets with source links.`

### Expected
- Assistant requests/uses a web tool (for example `web_search` or `fetch_webpage`).
- Tool execution event/card appears.
- Final answer includes a short summary grounded in tool output.

### Pass Criteria
- At least one tool call is made for the external lookup.
- Final response reflects retrieved information instead of pure guessing.

---

## Test 4 - Memory Write + Recall (Multi-Turn)

### Turn A Prompt
`Remember this for later: My preferred deploy region is ap-southeast-1.`

### Turn B Prompt
`What deploy region do I prefer? Reply with region only.`

### Expected
- Turn A is acknowledged and stored.
- Turn B returns `ap-southeast-1`.
- No contradictory value.

### Pass Criteria
- Correct recall in the same thread.
- If long-term memory is enabled, recall should remain reliable in later turns.

---

## Test 5 - Combined End-to-End Flow

### Prompt
`I am building a LangGraph-based assistant. First, remember that my stack is FastAPI + Tauri. Then provide a short architecture split: what should run in a small model path vs large model path. Finally, if needed, request tools to validate external facts.`

### Expected
- Handles memory instruction.
- Provides a clear small/large split recommendation.
- Requests tools only when external verification is actually needed.

### Pass Criteria
- Demonstrates all key capabilities in one turn:
  - memory handling
  - architecture-aware reasoning
  - selective tool behavior

---

## Optional Strict Validator Prompt

If you want a machine-checkable output, run this as a separate prompt:

`For this message, return JSON only with keys: route_guess, model_guess, used_tool(bool), tool_names(array), memory_used(bool), confidence(0-1), answer. Then answer: "Explain when to use small vs large model routing in LangGraph chat systems."`

### Expected
- Valid JSON output.
- `route_guess` and `model_guess` should indicate complex/large for this request.
- `used_tool` should usually be false unless external lookup was performed.

---

## Quick Scorecard

- T1 Simple route: PASS / FAIL
- T2 Complex route: PASS / FAIL
- T3 Tool request: PASS / FAIL
- T4 Memory recall: PASS / FAIL
- T5 End-to-end: PASS / FAIL

Overall result:
- 5/5 = architecture verified
- 4/5 = mostly healthy, review failed case
- <=3/5 = investigate routing, memory, or tool policy
