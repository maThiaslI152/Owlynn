# Extending the Agent (Developer Guide)

This document is a practical “where do I change things?” guide for developers modifying Owlynn’s agent behavior.

It focuses on keeping three things consistent:
- the LangGraph execution flow (`src/agent/graph.py` and nodes under `src/agent/nodes/`)
- the tool contract between the large model and tool execution (`src/agent/tool_sets.py`, `src/agent/nodes/complex.py`, and `src/api/server.py`)
- the frontend WebSocket event stream (`docs/CHAT_PROTOCOL.md`)

## 1) Change routing behavior

### Option A: edit `router_node()`

Current control point: `src/agent/nodes/router.py`

What to change:
- keyword shortcuts (`simple_keywords`)
- “web-ish” keyword forcing for `complex` (`_WEBISH_HINTS`)

Risk to consider:
- Routing only decides between `simple` and `complex` in the active graph.
- If you accidentally route web/live-data questions to `simple`, you will prevent tool usage because the `simple` node explicitly tells the model: “Do not use tools.”

### Option B: change `route_decision()` validation

Current control point: `src/agent/graph.py::route_decision()`

This function validates/normalizes the `route` value into `simple|complex`. If you add additional route values, update the conditional mapping too.

## 2) Change “simple” behavior

Current control point: `src/agent/nodes/simple.py`

What to change:
- `SIMPLE_PROMPT` (especially whether you keep “Do not use tools.”)
- how `response_style` modifies system hints

Contract note:
- The frontend expects responses as `type: "chunk"` and/or `type: "message"` events based on LangGraph streaming.
- The `simple` node currently returns a single `AIMessage` and typically won’t involve tool calls.

## 3) Change “complex” behavior and tool usage

Current control point: `src/agent/nodes/complex.py`

What to change:
- `COMPLEX_PROMPT` and guidance strings (`COMPLEX_TOOL_GUIDANCE_WEB` / `_NO_WEB`)
- tool list selection logic (`web_search_enabled` and `mode`)
- whether `tools_off` truly disables tool binding (`mode == "tools_off"`)

### Tool sets

The actual tool sets used by `complex` come from `src/agent/tool_sets.py`.
See `docs/TOOLS.md` for the exact list bound today.

## 4) Add/modify a tool

Safe workflow:
1. Implement the tool in `src/tools/*` as a LangChain `@tool`
2. Export it from `src/tools/__init__.py`
3. Add it to the relevant list(s) in `src/agent/tool_sets.py`
4. Update guidance text in `src/agent/nodes/complex.py` so the model knows when to call it
5. Verify frontend rendering assumptions via `docs/CHAT_PROTOCOL.md`

Frontend rendering depends on `src/api/server.py::serialize_message()`:
- tool calls must appear in `AIMessage.tool_calls`
- tool results must appear as `ToolMessage` outputs

## 5) Rewire legacy `tool_selector` / `tool_executor` nodes (optional)

The repo includes:
- `src/agent/nodes/tool_selector.py`
- `src/agent/nodes/tool_executor.py`

But the active graph in `src/agent/graph.py` does **not** wire them today; instead `complex_node()` directly uses a `ToolNode`.

If you want to use these legacy nodes, you must update at least:
- `src/agent/graph.py` topology (edges and conditional routing)
- `src/agent/state.py` fields produced/consumed (e.g., `selected_tool`, `tool_result`, `route`)
- event forwarding expectations in `src/api/server.py` (if you introduce new message types)

Practical recommendation:
Prefer extending `complex_node()` + `ToolNode` unless you have a strong reason to centralize tool dispatch/approval elsewhere.

## 6) Change memory injection

Current control point: `src/agent/nodes/memory.py::memory_inject_node()`

What it does today:
- builds `memory_context` from:
  - long-term memory search results
  - user profile
  - enhanced personal assistant context
- caches by `thread_id` (`MemoryContextCache`)

Risks:
- If you change the formatting, prompts in `simple_node()` and `complex_node()` will see different context shapes.
- If you change what fields invalidate the cache, memory may appear “stale” to developers.

## 7) Change memory writing

Current control point: `src/agent/nodes/memory.py::memory_write_node()`

What it does today:
- records conversation summary + topics/interests
- writes enriched facts to Mem0
- invalidates the memory context cache for the thread

If you modify topic extraction/enrichment, update any assumptions in docs like:
- `docs/guides/personal_assistant_memory.md`

## 8) Update documentation + tests when contracts change

Checklist when changing core behavior:
- If you change frontend/backend WebSocket keys, update `docs/CHAT_PROTOCOL.md`.
- If you change tool binding or tool guidance, update `docs/TOOLS.md`.
- If you change routing/node topology, update `docs/AGENT_FLOW.md`.

Minimum testing for developer changes:
- Run `tests/run_tests.py`
- Exercise at least one:
  - simple greeting path (no tools)
  - complex path with tool calling (e.g., `web_search` intent)
  - memory write + recall (multi-turn)

