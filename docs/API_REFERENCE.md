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

## Usage (Cloud Token Tracking)

- `GET /api/usage`
  - Returns cumulative session token usage for cloud (DeepSeek) API calls.
  - Response:
    ```json
    {
      "prompt_tokens": 5000,
      "completion_tokens": 2000,
      "total_tokens": 7000,
      "session_id": "..."
    }
    ```

## Chat (WebSocket)

See `docs/CHAT_PROTOCOL.md` for the payload and event contract.

- `WS /ws/chat/{thread_id}`

## Settings

### Profile
- `GET /api/profile`
  - Returns the merged profile object from `data/user_profile.json`.
- `POST /api/profile`
  - Updates profile keys from request body using `update_profile(field, value)`.
  - For runtime-impacting model fields (`small_*`, `medium_models`, `llm_*`, `large_*`, `cloud_*`, `deepseek_api_key`), the server clears LLM runtime caches (`LLMPool.clear()`) so subsequent runs pick up new keys without restart.
  - Response:
    - Full updated profile on full success, or
    - Partial-success envelope when some fields fail:
      ```json
      {
        "status": "partial_success",
        "profile": { "...": "..." },
        "updated_fields": ["name", "medium_models"],
        "errors": { "unknown_field": "Unknown profile field 'unknown_field'" }
      }
      ```

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
      "show_tool_execution": true,
      "cloud_escalation_enabled": true,
      "cloud_anonymization_enabled": true,
      "router_hitl_enabled": true,
      "router_clarification_threshold": 0.6,
      "custom_sensitive_terms": [],
      "redis_url": "redis://localhost:6379",
      "lm_studio_fold_system": true
    }
    ```
- `POST /api/advanced-settings`
  - Body keys updated: `temperature`, `top_p`, `max_tokens`, `top_k`, `streaming_enabled`, `show_thinking`, `show_tool_execution`, `cloud_escalation_enabled`, `cloud_anonymization_enabled`, `router_hitl_enabled`, `router_clarification_threshold`, `custom_sensitive_terms`, `redis_url`, `lm_studio_fold_system`
  - Returns `{ "status": "ok" | "error", "message": "..." }`

### Unified settings payload
- `GET /api/unified-settings`
  - Returns merged profile + advanced settings payload for frontend bootstrap.
  - Includes:
    - profile identity and LLM config fields,
    - all advanced settings fields from `/api/advanced-settings`,
    - cloud budget defaults: `cloud_daily_token_limit` and `cloud_budget_warning_thresholds`,
    - masked `deepseek_api_key` (`••••••••` when configured, empty string otherwise).

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

## User Profile Fields (`data/user_profile.json`)

The following fields were added for the S/M(swap)/L architecture:

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `cloud_llm_base_url` | string | `"https://api.deepseek.com/v1"` | Base URL for the DeepSeek cloud API |
| `cloud_llm_model_name` | string | `"deepseek-chat"` | Cloud model name |
| `deepseek_api_key` | string | `""` | DeepSeek API key (env var `DEEPSEEK_API_KEY` takes priority) |
| `medium_models` | object | `{"default": "qwen/qwen3.5-9b", "vision": "zai-org/glm-4.6v-flash", "longctx": "LFM2 8B A1B GGUF Q8_0"}` | M-tier model key mapping |
| `cloud_escalation_enabled` | boolean | `true` | Allow routing to cloud when local models can't handle the task |
| `cloud_anonymization_enabled` | boolean | `true` | Scrub PII before sending to cloud API |
| `custom_sensitive_terms` | list | `[]` | Additional terms to anonymize for cloud requests |
| `router_hitl_enabled` | boolean | `true` | Allow router to ask clarifying questions when confidence is low |
| `router_clarification_threshold` | float | `0.6` | Confidence threshold below which router asks for clarification |
| `redis_url` | string | `"redis://localhost:6379"` | Redis URL for conversation checkpointing |

