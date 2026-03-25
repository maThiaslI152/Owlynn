# Tools & Tool Binding (Developer Reference)

This document explains which tools are available to the agent *in practice* and how that is reflected in the UI.

## 1) Tool sets bound by the active graph

The current LangGraph graph (`src/agent/graph.py`) routes only to:
- `simple` (small model)
- `complex` (large model)

`simple` does not bind tools and also uses a system prompt that tells the model: *“Do not use tools.”*

`complex` binds a curated list of tools depending on `web_search_enabled`, using:
- `src/agent/tool_sets.py`:
  - `COMPLEX_TOOLS_WITH_WEB`
  - `COMPLEX_TOOLS_NO_WEB`

Concretely, the large model receives:

- With web:
  - `web_search` (optional `focus_query` for snippet reranking)
  - `fetch_webpage` (optional `focus_query` for excerpt ranking on long pages; SSRF-safe URLs only)
  - `execute_python_code`
  - `read_workspace_file`
  - `recall_memories`
- Without web:
  - `execute_python_code`
  - `read_workspace_file`
  - `recall_memories`

These come from `src/agent/nodes/complex.py` and are bound via `.bind_tools(tools)` and executed via `ToolNode(tools)`.

## 2) Tools implemented in `src/tools/*` (broader capability)

The repo contains additional tool implementations beyond the small set above, for example:

- sandbox command execution (Podman):
  - `execute_sandboxed_shell`
- workspace file editing helpers:
  - `write_workspace_file`, `edit_workspace_file`, `delete_workspace_file`, etc.
- Lightpanda browser automation tools (optional dependency):
  - `lightpanda_fetch_page`, `lightpanda_execute_js`, `lightpanda_screenshot`, ...
- optional Lightpanda browser automation tools (see below)

`fetch_webpage` is now part of `COMPLEX_TOOLS_WITH_WEB` (wired in `tool_sets.py`). Other fetch/edit/sandbox tools may still be MCP-only or legacy unless listed in `tool_sets.py`.

## 3) Adding a new tool (the safe path)

To make a new tool available to the large model in the current architecture:

1. Implement the tool as a LangChain tool (decorated with `@tool`) in `src/tools/`.
2. Re-export it from `src/tools/__init__.py` so `src/agent/tool_sets.py` can import it.
3. Add it to one or both tool lists in `src/agent/tool_sets.py`.
4. Update `src/agent/nodes/complex.py` guidance text (`COMPLEX_TOOL_GUIDANCE_WEB` / `COMPLEX_TOOL_GUIDANCE_NO_WEB`) so the model knows when to use the tool.
5. Update `docs/TOOLS.md` and any UI assumptions if the tool output shape affects rendering.

## 4) How tool calls appear in the UI

The frontend renders tool UI based on backend-forwarded `message` events:
- When the AI produces tool calls, `src/api/server.py` forwards an `AIMessage` containing `tool_calls`.
- When tools execute (via `ToolNode`), the server forwards `ToolMessage` outputs.

Streaming text response is carried in separate `chunk` events.

So when you modify tool execution behavior:
- keep `serialize_message()` output compatible with `renderMessage()` expectations
- keep tool-call output in the `message` events (not as plain text chunks)

## 5) Legacy tool selector/executor nodes

The repo also includes `src/agent/nodes/tool_selector.py` and `src/agent/nodes/tool_executor.py`.

These are legacy code paths and are not currently part of `src/agent/graph.py`.

If you rewire the graph to use them:
- ensure state fields like `selected_tool` and `tool_result` are produced/consumed correctly
- update this doc because the set/order of bound tools may change

