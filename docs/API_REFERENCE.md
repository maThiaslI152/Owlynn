# API Reference (Developer Reference)

This file documents the backend endpoints exposed by `src/api/server.py`.

The implementation is primarily used by `frontend/script.js`, but this is written for developers modifying backend behavior.

## Base URL

`http://<host>:8000`

## Static/UI

- `GET /` serves the frontend `frontend/index.html`
- `GET /script.js` serves `frontend/script.js`
- `/static/*` serves static assets mounted from the `frontend/` directory

## Health

- `GET /api/health`
  - Response:
    ```json
    { "status": "ok", "agent": "ready" | "initializing" }
    ```

## Chat (WebSocket)

See `docs/CHAT_PROTOCOL.md` for the payload and event contract.

- `WS /ws/chat/{thread_id}`

## Settings

### System prompt / persona
- `GET /api/system-settings`
  - Returns:
    `{ "system_prompt": "...", "custom_instructions": "...", "name": "...", "tone": "..." }`
- `POST /api/system-settings`
  - Body keys used: `system_prompt`, `custom_instructions`, `name`, `tone`
  - Returns `{ "status": "ok" | "error", "message": "..." }`

### Memory toggles
- `GET /api/memory-settings`
  - Returns:
    `{ "short_term_enabled": true | false, "long_term_enabled": true | false }`
- `POST /api/memory-settings`
  - Body keys used: `short_term_enabled`, `long_term_enabled`
  - Returns `{ "status": "ok" | "error", "message": "..." }`

### Advanced inference / behavior
- `GET /api/advanced-settings`
  - Returns:
    ```json
    {
      "temperature": 0.7,
      "top_p": 0.9,
      "max_tokens": 2048,
      "top_k": 40,
      "streaming_enabled": true,
      "show_thinking": false,
      "show_tool_execution": true
    }
    ```
- `POST /api/advanced-settings`
  - Body keys updated: `temperature`, `top_p`, `max_tokens`, `top_k`, `streaming_enabled`, `show_thinking`, `show_tool_execution`
  - Returns `{ "status": "ok" | "error", "message": "..." }`

## Memory & personal assistant data

- `GET /api/memories` -> list raw stored memories (from memory manager)
- `POST /api/memories`
  - Body: `{ "fact": "..." }`
- `DELETE /api/memories`
  - Body: `{ "fact": "..." }`

Personal assistant/topic endpoints:
- `GET /api/topics` -> `{ "status": "ok", "topics": [...] }`
- `GET /api/interests` -> `{ "status": "ok", "interests": [...] }`
- `GET /api/conversations?limit=<int>` -> `{ "status": "ok", "conversations": [...] }`
- `GET /api/memory-context` -> `{ "status": "ok", "memory_context": "..." }`
- `POST /api/topics/track`
  - Body: `{ "topic": "string", "category": "string" }`
- `POST /api/interests/update`
  - Body: `{ "interests": { "<interest_name>": <count>, ... } }`

## Workspace files (project-scoped)

Project-scoping is handled by `get_project_workspace(project_id)` and enforced with path-prefix checks.

- `GET /api/files?sub_path=<string>&project_id=<string>`
  - Lists files/folders including a `status` field (`processed` if cached, otherwise `idle`)
- `GET /api/files/{filename}?sub_path=<string>&project_id=<string>`
  - `FileResponse` serving the raw file bytes
- `POST /api/upload?sub_path=<string>&project_id=<string>`
  - Multipart upload: `file: UploadFile`
- `DELETE /api/files/{filename}?sub_path=<string>&project_id=<string>`
  - Deletes file/folder and removes cached `.processed/<name>.{txt,md}`
- `POST /api/files/{filename}/rename`
  - Body: `{ "new_name": "...", "sub_path": "...", "project_id": "..." }`
- `POST /api/files/{filename}/move`
  - Body: `{ "current_sub_path": "...", "target_sub_path": "...", "project_id": "..." }`
- `POST /api/folders`
  - Body: `{ "name": "...", "sub_path": "...", "project_id": "..." }`

## Projects

- `GET /api/projects`
- `POST /api/projects`
  - Body: `{ "name": "...", "instructions": "..." }`
- `GET /api/projects/{project_id}`
- `POST /api/projects/{project_id}/chats`
  - Body: `{ "id": "...", "name": "..." }`
- `PUT /api/projects/{project_id}/chats/{chat_id}`
- `DELETE /api/projects/{project_id}/chats/{chat_id}`
- `DELETE /api/projects/{project_id}`

## Tool discovery

- `GET /api/tools`
  - Returns a list of tool metadata derived from `src/tools/tool_registry`

## Notes for developers

- WebSocket request payload keys are parsed in `websocket_endpoint()` and passed into the agent state:
  - `mode`, `web_search_enabled`, `response_style`, `project_id`
- If you change any key names in `buildChatWsPayload()` (frontend), update this doc and the server parsing logic together.

