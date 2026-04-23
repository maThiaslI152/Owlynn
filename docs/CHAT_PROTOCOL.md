# Chat & Events Protocol (Developer Reference)

This document defines the *developer-facing* JSON contract between:

- the frontend WebSocket client (`frontend/script.js`)
- the backend WebSocket handler (`src/api/server.py`)
- the LangGraph execution stream forwarded to the browser

Keeping this doc accurate prevents UI/backend drift when you modify nodes, tools, or streaming behavior.

## WebSocket endpoint

`ws://<host>:8000/ws/chat/<thread_id>`

`thread_id` is used as the LangGraph `configurable.thread_id` and is also the key for per-thread memory context caching (`src/agent/nodes/memory.py`).

## Client -> Server: send payloads

### 1) Normal chat message

The client sends a JSON *text* message (via `socket.send(JSON.stringify(...))`) with this shape:

```json
{
  "message": "string",
  "files": [
    {
      "name": "string",
      "type": "string (mime type or 'workspace_ref')",
      "data": "string (base64) // only for non-workspace files",
      "path": "string // optional (used by workspace references)"
    }
  ],
  "mode": "tools_on | tools_off",
  "web_search_enabled": true | false,
  "response_style": "normal | learning | concise | explanatory | formal",
  "project_id": "string"
}
```

Defaults applied by the server:

- `mode` defaults to `tools_on`
- `web_search_enabled` defaults to `true`
- `response_style` defaults to `normal`
- `project_id` defaults to `default`

### 2) Stop generation

The client can interrupt the active graph task:

```json
{ "type": "stop" }
```

The server cancels the background task for that `thread_id`.

### 3) Security approval response

```json
{ "type": "security_approval", "approved": true | false }
```

Used to resume HITL-gated sensitive tool calls.

### 4) Ask-user response (structured answers supported)

```json
{ "type": "ask_user_response", "answer": "string | object" }
```

`answer` is forwarded without string coercion so structured router choices
(for example `{ "route": "...", "toolbox": "..." }`) remain intact.

## File attachments: how the backend interprets `files[]`

Attachments arrive as objects inside the `files` array.

### A) Workspace references (already exist on disk)

The frontend can attach a workspace file without uploading bytes by sending:

```json
{
  "type": "workspace_ref",
  "path": "relative/path/in/workspace"
}
```

Server behavior:

- it does **not** write file bytes
- it appends a short marker to `user_input`:
`[Attached Workspace File: <path>]`
- the agent can later use `read_workspace_file` if it needs actual content

### B) Uploaded files (base64)

For all attachments that are not `workspace_ref`, the server:

1. base64-decodes `data`
2. saves the raw bytes into the active project workspace folder

Server behavior in `build_message_content()` depends on MIME/type:

- Images (`type` starts with `image/`):
  - forwarded inline to the model as a multimodal `image_url` part
- PDFs (`type == application/pdf` or filename ends with `.pdf`):
  - the model is **not** given inline extracted text
  - instead the server injects an instruction like:
  `[File: <name> uploaded to workspace. Use read_workspace_file tool to read it if needed.]`
  - the expectation is that the model will call `read_workspace_file`, which reads from the `.processed/` cache when available
- Other non-image files:
  - same as PDFs: injected as a workspace-read instruction (no inline content)
  - use `read_workspace_file` if you need the contents inside the model

## Server -> Client: event types

The backend forwards two categories of messages:

1. **Custom status/error/file events** created by `GraphSession` and the file watcher
2. **LangGraph events** forwarded/translated into UI-friendly events (`chunk`, `message`)

### 1) `status`

```json
{ "type": "status", "content": "reasoning" | "idle" }
```

Sent:

- when a graph run starts
- when a graph run finishes (or a client disconnects)

### 2) `chunk`

```json
{ "type": "chunk", "content": "string", "metadata": {} }
```

Sent during streaming (LangGraph `on_chat_model_stream`) for nodes:

- `simple`
- `complex_llm`
- (legacy) `tool_executor` (not currently wired into the graph)

When a `TokenBudgetTracker` is active (initialized from the router's `token_budget`), each chunk includes an optional `metadata` field:

```json
{
  "type": "chunk",
  "content": "Hello, ",
  "metadata": {
    "tokens_used": 12,
    "budget_remaining": 3988
  }
}
```

- `tokens_used` — cumulative tokens consumed so far (estimated as `len(text) // 4` per chunk)
- `budget_remaining` — tokens remaining in the allocated budget

The `metadata` field is optional. Frontend code that does not handle `metadata` continues to work without errors.

### 3) `message`

```json
{
  "type": "message",
  "message": {
    "type": "ai" | "tool" | "human" | "...",
    "content": "string",
    "tool_calls": [ /* present on tool-calling AI messages */ ],
    "tool_name": "string",
    "tool_call_id": "string"
  }
}
```

How it appears in practice:

- When an AI model emits tool calls, the server forwards an `AIMessage` containing `tool_calls` so the frontend can render tool-call UI.
- When `ToolNode` executes tools, tool lifecycle/output is emitted via `tool_execution` events.

The exact fields come from `serialize_message()` in `src/api/server.py`.

### 4) `error`

```json
{ "type": "error", "content": "string" }
```

Emitted by `GraphSession._execute()` when graph execution raises an unhandled exception, or by `websocket_endpoint()` on connection-level failures.

Contract (tested via `test_ws_error_event_shape`):
- `type` must equal `"error"`
- `content` must be a non-empty string

### 5) `tool_execution`

The backend emits tool lifecycle events in the current implementation:

Running:

```json
{
  "type": "tool_execution",
  "status": "running",
  "tool_name": "string",
  "tool_call_id": "string|null",
  "input": "string|null"
}
```

Finished:

```json
{
  "type": "tool_execution",
  "status": "success|error",
  "tool_name": "string",
  "tool_call_id": "string|null",
  "output": "string|null",
  "error": "string|null",
  "duration": 1.23
}
```

These are derived from `AIMessage.tool_calls` + `ToolMessage` outputs in `websocket_endpoint()`.
Tool outputs are intentionally normalized into `tool_execution` events to avoid duplicate/misaligned chat message rendering.

### 6) `file_status`

```json
{ "type": "file_status", "name": "string", "status": "processed" | "deleted" }
```

Sent by `notify_file_processed()` to trigger UI refresh of the workspace file panel.

### 7) `model_info`

```json
{
  "type": "model_info",
  "model": "string",
  "swapping": true | false,
  "token_usage": {
    "prompt_tokens": 150,
    "completion_tokens": 320
  },
  "fallback_chain": [
    {
      "model": "large-cloud",
      "status": "failed",
      "reason": "API key invalid",
      "duration_ms": 42
    },
    {
      "model": "medium-default-fallback",
      "status": "success",
      "reason": "fallback",
      "duration_ms": 8
    }
  ]
}
```

Sent after `complex_llm` or `simple` node completes, when a `model_used` value is present in the node output (or when `fallback_chain` is present even without `model_used`).

Fields:

- `model` — the model that produced the response (e.g. `"medium-default"`, `"large-cloud"`)
- `swapping` — whether a model swap occurred
- `token_usage` — (optional) prompt and completion token counts from the API response; present only when the model reports usage
- `fallback_chain` — (optional) ordered list of model attempts; present only when `complex_llm_node` records fallback steps. Each entry is a `FallbackStep`:
  - `model` — non-empty model identifier
  - `status` — `"success"`, `"failed"`, or `"skipped"`
  - `reason` — human-readable explanation
  - `duration_ms` — time spent on this attempt (≥ 0)

The chain always has at least one entry and exactly one entry with `status == "success"`. Entries are ordered chronologically.

The `fallback_chain` field is populated by `complex_llm_node` and `simple_node` in every node output. The websocket event forwarder in `server.py` includes it in the `model_info` event payload when present.

`router_info` event is emitted following `router` node completion — see section 8 below.

### 8) `router_info` (implemented)

```json
{
  "type": "router_info",
  "metadata": {
    "route": "complex-default",
    "confidence": 0.87,
    "reasoning": "Code generation task detected",
    "swap_decision": "not_needed",
    "swap_from": "default",
    "swap_to": null,
    "classification_source": "llm_classifier",
    "token_budget": 4096,
    "cloud_available": true,
    "features": {
      "has_images": false,
      "task_category": "coding",
      "estimated_tokens": 320,
      "web_intent": false
    }
  }
}
```

Sent after the `router` node completes its routing decision, **before** the first `chunk` event for that message.

Metadata fields:

- `route` — the chosen route (e.g. `"simple"`, `"complex-default"`, `"complex-cloud"`, `"complex-vision"`, `"complex-longctx"`)
- `confidence` — classification confidence in [0.0, 1.0]
- `reasoning` — human-readable explanation of the routing decision
- `swap_decision` — `"kept"`, `"swapped"`, or `"not_needed"`
- `swap_from` / `swap_to` — previous and target model variants (null when no swap)
- `classification_source` — `"keyword_bypass"`, `"deterministic"`, `"llm_classifier"`, or `"hitl"`
- `token_budget` — allocated token budget for the response
- `cloud_available` — whether cloud escalation was an option
- `features` — key features that influenced the decision (never contains raw message text):
  - `has_images` — whether the input contained images
  - `task_category` — detected task type
  - `estimated_tokens` — estimated input token count
  - `web_intent` — whether web search intent was detected

The server forwarder (`server.py` `forward_events()`) emits this event at `on_chain_end` for the `router` node when `router_metadata` is present in the output. Non-serializable metadata fields are silently dropped with a warning log, so the event is never blocked by a single bad field.

Telemetry data source: `src/agent/nodes/router.py` — `router_node()` populates `router_metadata` on every return path. The `_build_router_metadata()` helper constructs the dict with fields guarded by `_check_cloud_available()`, `_has_image_content()`, and per-path reasoning strings.

### 9) `token_budget_update`

```json
{
  "type": "token_budget_update",
  "used": 1024,
  "total": 4096,
  "remaining": 3072,
  "percent": 0.25
}
```

Sent after streaming completes (when the `complex_llm` or `simple` node finishes), providing a final summary of token budget consumption.

Fields:

- `used` — total tokens consumed during streaming
- `total` — the allocated budget (from the router's `token_budget`)
- `remaining` — tokens remaining (`max(0, total - used)`)
- `percent` — fraction of budget consumed (can exceed 1.0 if streaming overruns the budget)

### 10) `cloud_budget_warning`

```json
{
  "type": "cloud_budget_warning",
  "used": 420000,
  "limit": 500000,
  "percent": 84.0,
  "level": "warning"
}
```

Sent when cumulative cloud token usage crosses a configured threshold. Thresholds default to 50%, 80%, and 95% of the daily limit.

Fields:

- `used` — cumulative cloud tokens consumed this session
- `limit` — the configured daily token limit (default 500,000)
- `percent` — usage as a percentage of the limit
- `level` — severity level:
  - `"info"` — usage crossed 50%
  - `"warning"` — usage crossed 80%
  - `"critical"` — usage crossed 95%

Each level is emitted at most once per session. Levels are emitted in order: `"info"` → `"warning"` → `"critical"`. If `cloud_daily_token_limit` is 0 or negative, no warnings are emitted.

### 11) `memory_updated`

```json
{
  "type": "memory_updated",
  "thread_id": "abc-123"
}
```

Sent after `memory_write_node` saves new data and invalidates the memory context cache for the thread.

Fields:

- `thread_id` — the thread whose memory context was updated

The frontend can use this event to know that the memory context is fresh and any cached state should be refreshed.

### 12) `context_summarized`

```json
{
  "type": "context_summarized",
  "summary": "bullet-point summary text...",
  "takeaways": ["Decision: use React for UI", "User prefers concise answers"],
  "messages_compressed": 12,
  "tokens_freed": 4500
}
```

Emitted when `auto_summarize_node` compresses older conversation history. Triggered when `active_tokens > 85%` of `context_window`.

Fields:
- `summary` — the generated summary text (3-5 bullet points)
- `takeaways` — individual takeaway strings parsed from the summary
- `messages_compressed` — number of messages that were compressed
- `tokens_freed` — estimated token count saved

Sent at `on_chain_end` for the `auto_summarize` node in the WebSocket event forwarder. The event appears between `memory_inject` and `router` node events in the stream. When no summarization is needed, the graph flows directly from `memory_inject` to `router` and no `context_summarized` event is emitted.

## REST API: Consolidated Settings

### `GET /api/unified-settings`

Returns all user-facing settings in a single response, merging fields from `GET /api/profile` and `GET /api/advanced-settings`.

```json
{
  "name": "string",
  "preferred_language": "en",
  "response_style": "concise",

  "small_llm_base_url": "http://127.0.0.1:1234/v1",
  "small_llm_model_name": "liquid/lfm2.5-1.2b",
  "llm_base_url": "http://127.0.0.1:1234/v1",
  "llm_model_name": "qwen/qwen3.5-9b",
  "medium_models": {},
  "cloud_llm_base_url": "https://api.deepseek.com/v1",
  "cloud_llm_model_name": "deepseek-chat",
  "deepseek_api_key": "••••••••",

  "temperature": 0.7,
  "top_p": 0.9,
  "max_tokens": 2048,
  "top_k": 40,
  "streaming_enabled": true,
  "show_thinking": false,
  "show_tool_execution": true,
  "lm_studio_fold_system": true,

  "cloud_escalation_enabled": true,
  "cloud_anonymization_enabled": true,
  "router_hitl_enabled": true,
  "router_clarification_threshold": 0.6,
  "custom_sensitive_terms": [],
  "redis_url": "redis://localhost:6379",

  "cloud_daily_token_limit": 500000,
  "cloud_budget_warning_thresholds": [0.5, 0.8, 0.95]
}
```

Notes:

- `deepseek_api_key` is always masked (`"••••••••"` when present, `""` when absent) — the raw key is never returned.
- `cloud_daily_token_limit` defaults to 500,000 when not configured.
- `cloud_budget_warning_thresholds` defaults to `[0.5, 0.8, 0.95]` when not configured.
- The existing `GET /api/profile` and `GET /api/advanced-settings` endpoints remain unchanged for backward compatibility.
- If `get_profile()` raises an exception, the endpoint returns an error response and the frontend falls back to the individual endpoints.

## Reference: where to change the contract

- Client request payload: `frontend/script.js` (`buildChatWsPayload()`)
- WebSocket forwarding and serialization: `src/api/server.py` (`websocket_endpoint()`, `serialize_message()`)
- Streaming sources: `src/agent/nodes/simple.py`, `src/agent/nodes/complex.py`, and their tool calling behavior
- Tool-call payload content: `serialize_message()` output consumed by `renderMessage()`

