# Agent Flow (LangGraph + Nodes)

This reflects the current compiled graph in `src/agent/graph.py`.

## Current graph topology

Nodes:
- `memory_inject`
- `router`
- `simple`
- `complex_llm`
- `security_proxy`
- `tool_action`
- `memory_write`

Flow:
1. `memory_inject -> router`
2. `router -> simple` **or** `router -> complex_llm`
3. `simple -> memory_write -> END`
4. `complex_llm`:
   - if no tool calls: `memory_write -> END`
   - if tool calls: `security_proxy -> (tool_action or memory_write)`
5. approved tool calls: `tool_action -> complex_llm` (loop)

So the complex path is a secure cycle with mandatory policy/approval gate before tool execution.

## Node roles

### `memory_inject` (`src/agent/nodes/memory.py`)
- Builds `memory_context` and persona text.
- Uses `MemoryContextCache` keyed by thread.
- Pulls long-term memory search results + profile + enhanced personal assistant context.

### `router` (`src/agent/nodes/router.py`)
- Sets `route` to `simple` or `complex`.
- Fast keyword and “web/live-data intent” heuristics first.
- Falls back to small LLM JSON classification.
- Safe fallback: `complex`.

### `simple` (`src/agent/nodes/simple.py`)
- Small model, short direct answers, no tools.
- Injects `response_style` hint.
- Returns `model_used = "small"`.

### `complex_llm` (`src/agent/nodes/complex.py`)
- Large model reasoning step for the cyclic tool flow.
- Binds tools (unless `mode == tools_off`).
- Sets `pending_tool_calls` when tool calls are present.
- Applies fallback text when model output is blank.

### `security_proxy` (`src/agent/nodes/security_proxy.py`)
- Reviews pending tool calls against policy/approval.
- Sets approval state used by conditional routing.
- On denial, flow exits to `memory_write` without tool execution.

### `tool_action` (`src/agent/nodes/complex.py::complex_tool_action_node`)
- Executes approved tool calls via `ToolNode`.
- Appends tool messages.
- Can append a fetch retry nudge for weak static webpage results.
- Returns to `complex_llm` for next reasoning step.

### `memory_write` (`src/agent/nodes/memory.py`)
- Records conversation summary/topics/interests.
- Writes enriched facts to long-term memory.
- Invalidates per-thread memory cache.

## Tool binding source

Tool lists are defined in `src/agent/tool_sets.py`:
- `COMPLEX_TOOLS_WITH_WEB`
- `COMPLEX_TOOLS_NO_WEB`

These lists are used by both `complex_llm_node` and `complex_tool_action_node`, so keep them in sync with docs and policy.

