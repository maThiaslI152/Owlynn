# Architecture Overview

Owlynn is a local-first AI productivity agent built with **LangGraph** for orchestration and **FastAPI** for the backend. Optimized for Apple Silicon (M4 Air 24GB) with a three-tier S / M(swap) / L hybrid LLM architecture.

## Three-Tier LLM Architecture

The system operates under a hard VRAM constraint: the M4 Air 24GB unified memory can only hold the S model + one M-tier model + embeddings simultaneously. The three tiers are:

- **S (Small):** Always loaded. Handles routing, simple answers, chat titles, toolbox selection, and HITL clarification.
- **M (Medium):** Swappable local slot. Only one M-tier model loaded at a time; the SwapManager hot-swaps between three variants based on task type.
- **L (Large):** Cloud API. Used only when local models can't handle the task — frontier-quality reasoning, very large summarization, or when even the long-context local model is insufficient.

### Model Table

| Key | Model | Role | VRAM | Context Window |
|-----|-------|------|------|----------------|
| Small_LLM | `liquid/lfm2.5-1.2b` (GGUF Q4_K_M) | Routing, simple answers, chat titles | ~730 MB | 4,096 |
| Medium_Default | `qwen/qwen3.5-9b` (GGUF Q6_K) | General complex reasoning, tool calling | ~8.3 GB | 100,000 |
| Medium_Vision | `zai-org/glm-4.6v-flash` | Image/multimodal processing | ~8 GB | 131,072 |
| Medium_LongCtx | `LFM2 8B A1B GGUF Q8_0` | Extended context tasks | ~8 GB | 131,072 |
| Cloud_LLM | `deepseek-chat` (DeepSeek API) | Frontier-quality reasoning (cloud) | N/A | 131,072 |

Small_LLM and one M-tier model are served via LM Studio on port 1234 (OpenAI-compatible API). Cloud_LLM uses the DeepSeek API at `https://api.deepseek.com/v1`.

## Core Components

### 1. Orchestrator (LangGraph) — 5-Way Routing

```
memory_inject → router → simple → memory_write → END
                       → complex_llm ↔ security_proxy ↔ tool_action → memory_write → END
```

The router performs a **two-stage decision**:
1. **Stage 1:** Classify as `simple` vs `complex` (keyword heuristics + Small_LLM).
2. **Stage 2 (complex only):** Select the model variant:
   - Image attachments → `complex-vision`
   - Input tokens > 80% of Medium_Default context → `complex-longctx`
   - Input tokens > Medium_LongCtx context or frontier-quality indicators → `complex-cloud`
   - Default → `complex-default`
   - Prefer currently-loaded variant when borderline (avoid swap latency)


#### Graph Flow Diagram

```
memory_inject → router ──→ simple ──────────────────→ memory_write → END
                  │
                  ├──→ complex-default ──→ complex_llm ↔ security_proxy ↔ tool_action → memory_write → END
                  ├──→ complex-vision  ──→ complex_llm ↔ security_proxy ↔ tool_action → memory_write → END
                  ├──→ complex-longctx ──→ complex_llm ↔ security_proxy ↔ tool_action → memory_write → END
                  └──→ complex-cloud   ──→ complex_llm ↔ security_proxy ↔ tool_action → memory_write → END
```

- **memory_inject**: Loads user profile, persona, topics, interests, and long-term memory context.
- **router**: Small_LLM classifies the message and selects route + toolbox categories. Keyword heuristics bypass LLM for obvious cases. Conversations with tool history stay on `complex`.
- **simple**: Small_LLM gives short direct answers. No tools. Falls back to Medium_Default on failure.
- **complex_llm**: Selected M-tier or Cloud model with dynamically-bound tools. Emits tool calls or direct answers.
- **security_proxy**: Gates sensitive tools (file write/edit/delete, notebook). Auto-approves safe tools.
- **tool_action**: Executes approved tool calls via ToolNode, loops back to complex_llm.
- **memory_write**: Extracts topics/interests, saves to Mem0/ChromaDB, invalidates cache.

### 2. LLMPool (`src/agent/llm.py`)

Manages three cached instance slots:

| Slot | Method | Description |
|------|--------|-------------|
| `_small_llm` | `get_small_llm()` | Always-loaded Small_LLM. ~700 tok/s prompt, ~110 tok/s gen. |
| `_medium_llm` | `get_medium_llm(variant)` | Currently-loaded M-tier model. Returns cached instance if variant matches; triggers SwapManager if not. |
| `_cloud_llm` | `get_cloud_llm()` | DeepSeek API client. `streaming=True`, `max_tokens=8192`, `temperature=0.4`. |

- `_current_medium_variant` tracks which M-tier model is loaded (`"default"`, `"vision"`, `"longctx"`, or `None`).
- `get_large_llm()` is kept as an alias for `get_medium_llm("default")` for backward compatibility.
- `clear()` resets all slots and `_current_medium_variant`.
- API key resolution: `DEEPSEEK_API_KEY` env var → `deepseek_api_key` in User_Profile → cloud disabled.

### 3. SwapManager (`src/agent/swap_manager.py`)

Wraps the **LM Studio native API** (`http://127.0.0.1:1234/api/v1/`) for model load/unload. Uses `httpx.AsyncClient`.

**Key constraint:** Only one M-tier model loaded at a time. The swap sequence is:

1. Query `GET /api/v1/models` to get the `instance_id` of the currently loaded M-tier model.
2. Unload current model: `POST /api/v1/models/unload` with `{instance_id}`.
3. Load target model: `POST /api/v1/models/load` with `{model: target_model_key}`.
4. Poll `GET /api/v1/models` until target appears in `loaded_instances` (timeout: 120s, poll interval: 2s).

- If unload fails → proceed with load anyway (LM Studio may handle the conflict).
- If load fails or times out → raise `ModelSwapError`, caught by Complex_Node for fallback.
- Model key mapping read from `User_Profile["medium_models"]`.

### 4. ToolboxRegistry (`src/agent/tool_sets.py`)

Dynamic tool loading reduces token overhead by ~2000 tokens per turn. The router selects toolbox categories; only relevant tools are bound.

**5 Toolbox Categories:**

| Category | Tools |
|----------|-------|
| `web_search` | `web_search`, `fetch_webpage` |
| `file_ops` | `read_workspace_file`, `write_workspace_file`, `edit_workspace_file`, `list_workspace_files`, `delete_workspace_file` |
| `data_viz` | `create_docx`, `create_xlsx`, `create_pptx`, `create_pdf`, `notebook_run`, `notebook_reset` |
| `productivity` | `todo_add`, `todo_list`, `todo_complete`, `list_skills`, `invoke_skill` |
| `memory` | `recall_memories` |

**Always included:** `ask_user` (HITL escape hatch).

`resolve_tools(toolbox_names, web_search_enabled)` returns the union of requested toolboxes + always-included tools. Passing `"all"` returns the full tool set. When `web_search_enabled=False`, web tools are excluded regardless of selection.

### 5. AnonymizationEngine (`src/agent/anonymization.py`)

PII scrubbing for cloud-bound messages. Applies **only** when route is `complex-cloud` AND `cloud_anonymization_enabled` is `True`. Local M-tier models are trusted (data never leaves the machine).

**Flow:**
1. `anonymize(text, context)` → scans for sensitive patterns, replaces with `[CATEGORY_N]` placeholders, returns `(anonymized_text, mapping)`.
2. Send anonymized text to Cloud_LLM.
3. `deanonymize(response_text, mapping)` → restores placeholders to original values.

**Detection categories (priority order — longest match first):**
1. API keys/tokens (`sk-`, `key-`, `Bearer`, `ghp_`, 32+ char alphanumeric)
2. Email addresses
3. URLs with localhost ports
4. File system paths (`/Users/`, `/home/`, `C:\`, `~/`)
5. IP addresses (excluding `0.0.0.0`, `255.255.255.255`)
6. Phone numbers (international formats)
7. Known names (from User_Profile `name` field)
8. Custom sensitive terms (from User_Profile `custom_sensitive_terms`)

**Round-trip property:** `deanonymize(anonymize(text, ctx)[0], anonymize(text, ctx)[1]) == text`

### 6. Short-Term Memory: Redis Checkpointer

Conversation history persists across model swaps and server restarts via `langgraph-checkpoint-redis` (`AsyncRedisSaver`).

```python
# src/agent/graph.py
from langgraph_checkpoint_redis import AsyncRedisSaver

checkpointer = AsyncRedisSaver(url=REDIS_URL)
await checkpointer.setup()
# Falls back to MemorySaver if Redis is unavailable
```

- Redis runs as a container alongside ChromaDB and SearXNG in `docker-compose.yml`.
- Each conversation thread maintains isolated state via `Thread_ID`.
- Messages, routing metadata, and tool call history are all preserved across M-tier swaps.

### 7. Long-Term Memory

- **Mem0 + ChromaDB** (multilingual-e5-small embeddings, ~500 MB VRAM)
- **Data files**: JSON storage for topics, interests, conversations, todos
- Memory injection/write pipeline is model-agnostic — operates on conversation content regardless of which LLM produced it.

### 8. Skills System

Reusable prompt templates in `skills/*.md`. Zero token cost until invoked.
Triggers match user intent keywords. Currently: research, summarize, briefing,
comparison, visualization, meeting notes, email, report, presentation, rewriter, brainstorm.

### 9. Web Search Pipeline

```
Tier 0:   wttr.in (weather fast path)
Tier 0.5: SearXNG (self-hosted, localhost:8888)
Tier 1A:  Brave/Serper/Tavily APIs (if keys set)
Tier 1B:  curl_cffi (DDG/Bing HTML scraping)
Tier 2:   DDGS Python library / httpx fallbacks
Tier 3:   Playwright (full browser)
```

### 10. Frontend

- Tauri desktop app loading from FastAPI (http://127.0.0.1:8000)
- Vanilla HTML/JS/CSS with Tailwind utilities
- All dependencies vendored locally (offline-capable)
- WebSocket streaming for real-time responses
- Tier-colored model badges: gray (small), blue (medium), purple (cloud), orange (fallback)
- Cloud token indicator: `↑{prompt} ↓{completion}` next to badge
- Swap indicator: transient message during M-tier model loading
- Router clarification: choices rendered as clickable buttons via `handleAskUserInterrupt`

### 11. Infrastructure

- **Docker Compose**: Redis (port 6379, 512 MB cap), ChromaDB (port 8100), SearXNG (port 8888)
- **LM Studio**: Local LLM inference server (port 1234)
- **Redis**: `redis:7-alpine` with AOF persistence, stores conversation checkpoints
- **No sandbox/container needed for tool execution** — all tools run natively

### 12. Tiered Fallback Chain

The system ensures users always get a response:

1. **Cloud failure** → Retry with Medium_Default. HTTP 401/403 → suggest checking API key. HTTP 429 → retry after 2s, then Medium_Default.
2. **Medium_Vision failure** → Fall back to Medium_Default.
3. **Medium_LongCtx failure** → Try Cloud_LLM first, then Medium_Default with truncated context.
4. **Medium_Default failure** → Return error suggesting user check LM Studio.
5. **Small_LLM failure** → Fall back to Medium_Default.
6. **Model swap failure (ModelSwapError)** → Use currently-loaded M-tier variant.

All fallbacks set `model_used` to a descriptive value with `-fallback` suffix.
