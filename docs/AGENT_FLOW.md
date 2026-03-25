# Agent Flow (LangGraph + Nodes)

This document explains the runtime control flow for a single chat turn, based on the current graph wiring in `src/agent/graph.py`.

## Graph topology (the current default)

`src/agent/graph.py` builds a LangGraph `StateGraph` with these nodes:

- `memory_inject` (enrich prompt context)
- `router` (decide between `simple` vs `complex`)
- `simple` (small model, no tools)
- `complex_llm` (large model, optional tools; may emit tool calls)
- `security_proxy` (policy / HITL gate before tool execution)
- `tool_action` (runs `ToolNode` for approved calls)
- `memory_write` (persist conversation + update long-term memory)

Edges (simplified): `memory_inject -> router -> (simple | complex_llm)`; `complex_llm` may loop through `security_proxy` and `tool_action` before ending at `memory_write -> END`.

Legacy `complex_node()` (single-shot tools + second LLM call in one node) may still exist in `complex.py` but the **compiled graph** uses `complex_llm_node` + `complex_tool_action_node` as above.

## Web research and excerpt RAG

When `web_search_enabled` is true, the complex tool list includes `web_search` and `fetch_webpage`. Both accept an optional `focus_query`; when set, `web_search` reranks result snippets and `fetch_webpage` can return embedding-ranked excerpts (`[1]`, `[2]`, …) for long pages instead of only a truncated body. Implementation: [`src/tools/web_retrieval.py`](../src/tools/web_retrieval.py). HTTP fetches use SSRF checks in [`src/tools/url_policy.py`](../src/tools/url_policy.py). Tune behavior with `WEB_RAG_*` env vars (see [`src/config/settings.py`](../src/config/settings.py)).

## Node-by-node behavior

### `memory_inject` (`src/agent/nodes/memory.py`)

Purpose: produce the `memory_context` string and persona summary passed into system prompts.

Key behaviors:
- Uses `MemoryContextCache` keyed by `thread_id` to avoid rebuilding context repeatedly.
- Retrieves:
  - long-term memory search results (Mem0 / `src/memory/long_term.py`)
  - structured user profile (`src/memory/user_profile.py`)
  - enhanced memory context (`get_memory_context_for_prompt()` from the personal assistant module)
- Returns a partial state update:
  - `memory_context`: formatted context block
  - `persona`: persona role/summary string

### `router` (`src/agent/nodes/router.py`)

Purpose: decide `route` = `simple` or `complex`.

Key behaviors:
- If `web_search_enabled` is `true`, router checks for “web-ish” keywords and forces `complex` (fast path for live-data intents).
- Otherwise it:
  - checks a keyword list (greetings/thanks/bye -> `simple`)
  - falls back to the small LLM routing prompt (`ROUTER_PROMPT`) and parses JSON
- Safe default on parsing errors: `complex`

The router returns `{"route": "<simple|complex>"}`.

### `simple` (`src/agent/nodes/simple.py`)

Purpose: quick answers using the small model without tool access.

Key behaviors:
- Builds a system prompt that explicitly says: *“Do not use tools.”*
- Includes:
  - `memory_context` when present
  - `response_style` instruction hint (from `src/agent/response_styles.py`)
- Calls the small model (`get_small_llm()`)
- Returns:
  - `messages`: a single `AIMessage`
  - `model_used`: `"small"`

### `complex` (`src/agent/nodes/complex.py`)

Purpose: deeper reasoning and optionally tool use (large model).

Key behaviors:
- If `mode == "tools_off"`:
  - calls large model with no tool binding
  - returns a single `AIMessage`
- Otherwise (`tools_on`):
  - selects a tool list depending on `web_search_enabled`:
    - with web: `COMPLEX_TOOLS_WITH_WEB`
    - without web: `COMPLEX_TOOLS_NO_WEB`
  - binds tools to the large model via `.bind_tools(tools)`
  - first calls the large model
  - if the model includes tool calls:
    - executes them with `ToolNode`
    - calls the large model again to produce the final response grounded in tool results

Returns:
- `messages`: streaming-compatible sequence of messages produced by the large model + tool outputs
- `model_used`: `"large"`

### `memory_write` (`src/agent/nodes/memory.py`)

Purpose: persist per-turn conversation signals into the personal assistant memory system.

Key behaviors:
- Extracts last human and last AI messages for the turn.
- Calls `record_conversation()` in a background thread.
- Extracts topics/interests with `TopicExtractor` and enriches facts with `MemoryEnricher`.
- Adds the enriched fact to Mem0 (`memory.add(..., infer=True)`).
- Invalidates `MemoryContextCache` for `thread_id`.

Note:
- The current implementation returns `{}` (no additional state fields written by this node).

## Legacy / unused code paths (important when modifying)

The repo still contains:
- `src/agent/nodes/tool_selector.py`
- `src/agent/nodes/tool_executor.py`

These are not currently wired into `src/agent/graph.py`.

If you rewire graph edges to use them, you must:
- align the state fields (`selected_tool`, `tool_result`, `route`)
- update the frontend event handling expectations if you introduce new event types
- update this document to reflect the new control flow

