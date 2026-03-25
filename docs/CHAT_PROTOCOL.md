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

Note: the current server implementation sends `content` and (effectively) omits metadata.

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
- When `ToolNode` executes tools, the server forwards `ToolMessage` outputs so the frontend can render tool result UI.

The exact fields come from `serialize_message()` in `src/api/server.py`.

### 4) `error`

```json
{ "type": "error", "content": "string" }
```

Current behavior:
- `GraphSession` emits `content` only (no `title`/`details`).
- the frontend tolerates this, but if you enhance errors you can standardize `title`/`details` here.

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

### 6) `file_status`

```json
{ "type": "file_status", "name": "string", "status": "processed" | "deleted" }
```

Sent by `notify_file_processed()` to trigger UI refresh of the workspace file panel.

## Events the frontend listens to (but the backend may not currently emit)

- `model_info`: the frontend listens, but current backend code does not send it.

If you add those events in backend nodes, document the exact payload shapes in this file.

## Reference: where to change the contract

- Client request payload: `frontend/script.js` (`buildChatWsPayload()`)
- WebSocket forwarding and serialization: `src/api/server.py` (`websocket_endpoint()`, `serialize_message()`)
- Streaming sources: `src/agent/nodes/simple.py`, `src/agent/nodes/complex.py`, and their tool calling behavior
- Tool-call payload content: `serialize_message()` output consumed by `renderMessage()`

