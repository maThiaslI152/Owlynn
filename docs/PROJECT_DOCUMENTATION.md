# Owlynn — Complete Project Documentation

Owlynn is a private, local-first AI productivity agent built for Apple Silicon (M4 Air 24 GB). It runs entirely on your machine using LangGraph orchestration, a three-tier hybrid LLM architecture, and a Cowork-style tool system with a Tauri desktop frontend.

---

## Table of Contents

1. [System Architecture](#1-system-architecture)
2. [Three-Tier LLM Architecture](#2-three-tier-llm-architecture)
3. [LangGraph Orchestration](#3-langgraph-orchestration)
4. [Router System](#4-router-system)
5. [LLM Pool & Model Swapping](#5-llm-pool--model-swapping)
6. [Tool System](#6-tool-system)
7. [Security Proxy](#7-security-proxy)
8. [Memory System](#8-memory-system)
9. [Skills System](#9-skills-system)
10. [Web Search Pipeline](#10-web-search-pipeline)
11. [Cloud Anonymization](#11-cloud-anonymization)
12. [Backend API](#12-backend-api)
13. [Frontend](#13-frontend)
14. [Infrastructure](#14-infrastructure)
15. [Configuration](#15-configuration)
16. [Test Suite](#16-test-suite)
17. [Project Structure](#17-project-structure)
18. [Developer + AI Agent Documentation Map](#18-developer--ai-agent-documentation-map)
19. [Current Progress Snapshot](#19-current-progress-snapshot)
20. [Current Bug Tracker](#20-current-bug-tracker)
21. [Future Plan](#21-future-plan)
22. [Roadmap](#22-roadmap)

---

## 1. System Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        Tauri Desktop App                        │
│  frontend/index.html + script.js + style.css (vendored deps)   │
└──────────────────────────┬──────────────────────────────────────┘
                           │ WebSocket (ws://127.0.0.1:8000)
┌──────────────────────────▼──────────────────────────────────────┐
│                    FastAPI Backend (port 8000)                   │
│  src/api/server.py — REST + WebSocket + static file serving     │
└──────────────────────────┬──────────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────────┐
│                   LangGraph Agent Engine                         │
│  7-node stateful cyclic graph with Redis checkpointing          │
│                                                                  │
│  memory_inject → router → simple ──────────→ memory_write → END │
│                         → complex_llm ↔ security_proxy          │
│                                       ↔ tool_action             │
│                                       → memory_write → END      │
└──────┬──────────────┬───────────────┬───────────────────────────┘
       │              │               │
┌──────▼──────┐ ┌─────▼─────┐ ┌──────▼──────┐
│  LM Studio  │ │ DeepSeek  │ │   Docker    │
│  port 1234  │ │ Cloud API │ │  Services   │
│ S + M models│ │           │ │ Redis/Qdrant│
│             │ │           │ │ /SearXNG    │
└─────────────┘ └───────────┘ └─────────────┘
```

The system operates under a hard VRAM constraint: the M4 Air 24 GB unified memory holds the Small model + one Medium-tier model + embeddings simultaneously. Only one M-tier model is loaded at a time; the SwapManager hot-swaps between variants via the LM Studio native API.

---

## 2. Three-Tier LLM Architecture

| Tier | Key | Model | Role | VRAM | Context |
|------|-----|-------|------|------|---------|
| S (Small) | `Small_LLM` | `liquid/lfm2.5-1.2b` (Q4_K_M) | Routing, simple answers, chat titles | ~730 MB | 4,096 |
| M (Medium) | `Medium_Default` | `qwen/qwen3.5-9b` (Q6_K) | General complex reasoning, tool calling | ~8.3 GB | 100,000 |
| M (Medium) | `Medium_Vision` | `zai-org/glm-4.6v-flash` | Image/multimodal processing | ~8 GB | 131,072 |
| M (Medium) | `Medium_LongCtx` | `lfm2-8b-a1b` (Q8_0) | Extended context tasks | ~8 GB | 131,072 |
| L (Cloud) | `Cloud_LLM` | `deepseek-chat` (DeepSeek API) | Frontier-quality reasoning | N/A | 131,072 |

Small_LLM and one M-tier model are served via LM Studio on port 1234 (OpenAI-compatible API). Cloud_LLM uses the DeepSeek API.

---

## 3. LangGraph Orchestration

Defined in `src/agent/graph.py`. The graph has 7 nodes:

| Node | Module | Purpose |
|------|--------|---------|
| `memory_inject` | `src/agent/nodes/memory.py` | Loads user profile, persona, topics, interests, long-term memory. Caches per thread (5-min TTL). |
| `router` | `src/agent/nodes/router.py` | Two-stage classification: simple vs complex, then variant selection. Keyword bypass for obvious cases. |
| `simple` | `src/agent/nodes/simple.py` | Small LLM gives short direct answers. No tools. Falls back to Medium_Default on failure. |
| `complex_llm` | `src/agent/nodes/complex.py` | Selected M-tier or Cloud model with dynamically-bound tools. Emits tool calls or direct answers. |
| `security_proxy` | `src/agent/nodes/security_proxy.py` | Gates sensitive tools. Auto-approves safe tools. HITL interrupt for sensitive ones. |
| `tool_action` | `src/agent/nodes/complex.py` | Executes approved tool calls via ToolNode, loops back to complex_llm. |
| `memory_write` | `src/agent/nodes/memory.py` | Extracts topics/interests, saves to Mem0/Qdrant, invalidates cache. |

State is defined in `src/agent/state.py` as `AgentState(TypedDict)` with fields for messages, route, model_used, memory_context, persona, toolboxes, token_budget, security state, and cloud token tracking.

---

## 4. Router System

The router (`src/agent/nodes/router.py`) performs a two-stage decision:

**Stage 1 — Simple vs Complex:**
- Keyword bypass: greetings/thanks → `simple`
- Web intent detection (weather, prices, news) → `complex`
- Workspace attachments → `complex`
- Conversation with tool history → stays `complex`
- Fallback: Small LLM JSON classification with confidence score

**Stage 2 — Complex Variant Selection (`_resolve_complex_route`):**
1. Image attachments → `complex-vision`
2. Input tokens > 80% of Medium_LongCtx → `complex-cloud`
3. Input tokens > 80% of Medium_Default → `complex-longctx`
4. Frontier-quality indicators (proofs, theorems) → `complex-cloud`
5. Default → `complex-default`

**HITL Clarification:** When confidence < threshold (default 0.6) and `router_hitl_enabled`, the router triggers an `interrupt()` presenting 5 choices to the user.

**Enhanced Router Package** (`src/agent/router/`):
- `models.py` — `TaskFeatures`, `RouteClassification`, `RouterConfig` dataclasses
- `feature_extractor.py` — Extracts structured features from user input
- `classifier.py` — `RouteClassifier` using Small LLM with structured prompt
- `selector.py` — `RouteSelector` with swap-avoidance logic
- `budget.py` — Token budget estimation per route

**Token Budget Tiers:**
| Route | Max Budget | Context Window |
|-------|-----------|----------------|
| `simple` | 512 | 4,096 |
| `complex-default` / `complex-vision` | 8,192 | 100,000 |
| `complex-longctx` | 8,192 | 131,072 |
| `complex-cloud` | 16,384 | 131,072 |

---

## 5. LLM Pool & Model Swapping

**LLMPool** (`src/agent/llm.py`) manages three cached instance slots:

| Slot | Method | Behavior |
|------|--------|----------|
| `_small_llm` | `get_small_llm()` | Always-loaded. Created once, cached forever. |
| `_medium_llm` | `get_medium_llm(variant)` | Returns cached if variant matches `_current_medium_variant`. Otherwise triggers SwapManager. |
| `_cloud_llm` | `get_cloud_llm()` | DeepSeek API client. Raises `CloudUnavailableError` if no API key. |

**SwapManager** (`src/agent/swap_manager.py`) wraps the LM Studio native API:

1. `GET /api/v1/models` — query loaded instances
2. `POST /api/v1/models/unload` — best-effort unload of all M-tier instances
3. `POST /api/v1/models/load` — load target model
4. Poll until target appears in `loaded_instances` (timeout: 120s, poll: 2s)

Raises `ModelSwapError` on timeout or load failure.

**Fallback Chain:**
- Cloud failure → retry (429), then Medium_Default. Auth errors append API key warning.
- Vision failure → Medium_Default
- LongCtx failure → try Cloud, then Medium_Default
- Small failure → Medium_Default
- All fallbacks set `model_used` with `-fallback` suffix.

---

## 6. Tool System

Defined in `src/agent/tool_sets.py`. 20 tools organized into 5 dynamic toolbox categories:

| Category | Tools |
|----------|-------|
| `web_search` | `web_search`, `fetch_webpage` |
| `file_ops` | `read_workspace_file`, `write_workspace_file`, `edit_workspace_file`, `list_workspace_files`, `delete_workspace_file` |
| `data_viz` | `create_docx`, `create_xlsx`, `create_pptx`, `create_pdf`, `notebook_run`, `notebook_reset` |
| `productivity` | `todo_add`, `todo_list`, `todo_complete`, `list_skills`, `invoke_skill` |
| `memory` | `recall_memories` |

`ask_user` is always included regardless of toolbox selection.

`resolve_tools(toolbox_names, web_search_enabled)` returns the union of requested toolboxes. Passing `"all"` returns the full set. When `web_search_enabled=False`, web tools are excluded.

**Tool Implementations:**
- `src/tools/web_tools.py` — Tiered web search + static/dynamic fetch
- `src/tools/core_tools.py` — File management + memory recall
- `src/tools/doc_generator.py` — DOCX, XLSX, PPTX, PDF creation
- `src/tools/notebook.py` — Stateful Python REPL (variables persist between cells)
- `src/tools/todo.py` — Persistent task tracking (JSON-backed)
- `src/tools/skills.py` — Skill template loading and invocation
- `src/tools/ask_user.py` — HITL clarification with choice buttons
- `src/tools/mcp_client.py` — MCP server integration as LangChain tools

---

## 7. Security Proxy

`src/agent/nodes/security_proxy.py` sits between LLM tool-call planning and execution.

**Sensitive Tools:** `write_workspace_file`, `edit_workspace_file`, `delete_workspace_file`, `notebook_run`

**Dangerous Patterns:** `rm -rf`, `curl`, `wget`, `sudo`, `chmod`, `chown`, `ssh`, `scp`

- Safe calls → auto-approved
- Sensitive calls → HITL interrupt (approval modal in frontend)
- Denied → flow exits to memory_write with denial message

---

## 8. Memory System

**Short-Term:** Redis checkpointer (`langgraph-checkpoint-redis`) persists conversation state across model swaps and server restarts. Falls back to `MemorySaver` if Redis unavailable.

**Long-Term:** Mem0 + Qdrant (multilingual-e5-small embeddings). Project-scoped isolation: non-default projects use `project:<id>` as user_id.

**Personal Assistant Memory** (`src/memory/personal_assistant.py`):
- Topic extraction with regex patterns (programming languages, frameworks, databases, etc.)
- Interest detection (learning, debugging, optimization, architecture, etc.)
- Time-decayed relevance scoring (topic half-life: 14 days, interest half-life: 21 days)
- Current focus detection (3-day window)
- Conversation summarization and recording
- Context builder for system prompt injection

**Data Files** (`data/`):
- `user_profile.json` — User preferences, LLM config, cloud settings
- `persona.json` — Agent name, role, tone
- `memories.json` — Cross-session facts (max 200)
- `topics.json` — Tracked topics with time decay
- `interests.json` — Detected interests with time decay
- `conversations.json` — Conversation summaries (last 100)
- `projects.json` — Project definitions with files and chats

---

## 9. Skills System

11 reusable prompt templates in `skills/*.md` with YAML front-matter:

| Skill | Triggers |
|-------|----------|
| Research Assistant | research, deep dive, investigate |
| Document Summarizer | summarize, summary, tldr, key points |
| Morning Briefing | briefing, morning, daily summary |
| Visual Comparison | compare, versus, side by side |
| Data Visualization | chart, graph, plot, visualize, dashboard |
| Meeting Notes | meeting notes, action items, minutes |
| Email Drafter | draft email, write email, compose email |
| Report Generator | create report, write report, generate report |
| Presentation Builder | create presentation, slides, deck, pptx |
| Content Rewriter | rewrite, rephrase, improve writing |
| Brainstorm | brainstorm, ideas, suggest, what if |

Zero token cost until invoked. The LLM calls `invoke_skill` when user intent matches triggers.

---

## 10. Web Search Pipeline

`src/tools/web_tools.py` implements a tiered reliability pipeline:

```
Tier 0:   wttr.in (weather fast path)
Tier 0.5: SearXNG (self-hosted, localhost:8888, no API keys)
Tier 1A:  Brave/Serper/Tavily APIs (if keys configured)
Tier 1B:  curl_cffi (DDG/Bing HTML scraping)
Tier 2:   DDGS Python library / httpx fallbacks
Tier 3:   Playwright (full browser, for SPA/JS-heavy pages)
```

**Web RAG** (`src/tools/web_retrieval.py`): Embedding-based chunk ranking for fetched pages using LM Studio's `/v1/embeddings` endpoint. Chunks text into overlapping segments, embeds with `nomic-embed-text-v1.5`, ranks by cosine similarity to focus query.

**Bot Detection:** Cloudflare Turnstile, Akamai, CAPTCHA, and other anti-bot challenges are detected and trigger fallback to dynamic fetching.

---

## 11. Cloud Anonymization

`src/agent/anonymization.py` scrubs PII before sending to DeepSeek API. Only active when `route == "complex-cloud"` and `cloud_anonymization_enabled == True`.

**Detection categories (priority order):**
1. API keys/tokens (sk-, key-, Bearer, ghp_, 32+ char alphanumeric)
2. Email addresses
3. Localhost URLs with ports
4. File system paths (/Users/, /home/, ~/, C:\)
5. IP addresses (excluding 0.0.0.0, 255.255.255.255)
6. Phone numbers (international formats)
7. Known names (from user profile)
8. Custom sensitive terms (from user profile)

Replaces with `[CATEGORY_N]` placeholders. Response is deanonymized before returning to user. Round-trip property: `deanonymize(anonymize(text)) == text`.

---

## 12. Backend API

FastAPI server at `src/api/server.py` (port 8000).

**Key Endpoints:**

| Method | Path | Purpose |
|--------|------|---------|
| `WS` | `/ws/chat/{thread_id}` | WebSocket streaming chat |
| `GET` | `/api/health` | Health check |
| `GET/POST` | `/api/profile` | User profile CRUD |
| `GET/POST` | `/api/system-settings` | System prompt + persona |
| `GET/POST` | `/api/memory-settings` | Memory toggles |
| `GET/POST` | `/api/advanced-settings` | Inference parameters |
| `GET/POST/DELETE` | `/api/memories` | Long-term memory CRUD |
| `GET` | `/api/topics` | Tracked topics |
| `GET` | `/api/interests` | Detected interests |
| `GET` | `/api/usage` | Cloud token usage |
| `GET/POST/DELETE` | `/api/files` | Workspace file management |
| `POST` | `/api/upload` | File upload |
| `GET/POST/DELETE` | `/api/projects` | Project CRUD |
| `GET` | `/api/tools` | Tool discovery |

**WebSocket Protocol:** See `docs/CHAT_PROTOCOL.md`. Events: `status`, `chunk`, `message`, `error`, `tool_execution`, `file_status`.

**File Processor** (`src/api/file_processor.py`): Background watchdog that auto-processes uploaded files into `.processed/` cache. Supports PDF, DOCX, XLSX, PPTX, EPUB, RTF, JSON, XML, YAML, TOML, HTML, SQLite, archives, source code, and plain text.

---

## 13. Frontend

Vanilla HTML/JS/CSS with Tailwind utilities. All dependencies vendored locally (offline-capable).

**Views:**
- Welcome — composer with recent chats
- Chat — streaming messages with tool execution cards
- Chats — searchable chat list with batch operations
- Projects — project management with file viewer
- Customize — skills and connectors

**Key Features:**
- WebSocket streaming for real-time responses
- Model badges: gray (small), blue (medium), purple (cloud), orange (fallback)
- Cloud token indicator: `↑{prompt} ↓{completion}`
- Swap indicator during M-tier model loading
- Router clarification: choices rendered as clickable buttons
- Security approval modal for sensitive tool calls
- Drag-and-drop file upload
- Spotlight search (Cmd+K)
- Dark theme with gold accent (`#b08d3e`)

**Vendored Dependencies:** Tailwind CSS, DOMPurify (XSS protection), Marked (markdown rendering), Mammoth (DOCX rendering).

---

## 14. Infrastructure

**Docker Compose** (`docker-compose.yml`):

| Service | Image | Port | Purpose |
|---------|-------|------|---------|
| Redis | `redis:7-alpine` | 6379 | Conversation checkpointing (AOF persistence, 512 MB cap) |
| Qdrant | `qdrant/qdrant:latest` | 8100 | Long-term memory vector store |
| SearXNG | `searxng/searxng:latest` | 8888 | Self-hosted metasearch (no API keys) |

**LM Studio:** Local LLM inference server on port 1234 (OpenAI-compatible API).

**MCP Integration:** `mcp_config.json` configures external MCP servers (currently: sequential-thinking). Tools are dynamically ingested as LangChain tools via `src/tools/mcp_client.py`.

---

## 15. Configuration

**User Profile** (`data/user_profile.json`):

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `name` | string | `"User"` | Display name |
| `preferred_language` | string | `"en"` | Response language |
| `response_style` | string | `"concise"` | concise / detailed / step_by_step |
| `small_llm_base_url` | string | `"http://127.0.0.1:1234/v1"` | Small LLM endpoint |
| `small_llm_model_name` | string | `"liquid/lfm2.5-1.2b"` | Small model name |
| `medium_models` | object | `{default, vision, longctx}` | M-tier model key mapping |
| `cloud_llm_base_url` | string | `"https://api.deepseek.com/v1"` | Cloud API endpoint |
| `deepseek_api_key` | string | `""` | DeepSeek API key |
| `cloud_escalation_enabled` | boolean | `true` | Allow cloud routing |
| `cloud_anonymization_enabled` | boolean | `true` | PII scrubbing for cloud |
| `router_hitl_enabled` | boolean | `true` | Router clarification |
| `router_clarification_threshold` | float | `0.6` | Confidence threshold |
| `redis_url` | string | `"redis://localhost:6379"` | Redis URL |

**Environment Variables** (`.env`):
- `DEEPSEEK_API_KEY` — Cloud API key (overrides profile)
- `REDIS_URL` — Redis connection string
- `SEARXNG_URL` — SearXNG instance URL
- `BRAVE_SEARCH_API_KEY`, `SERPER_API_KEY`, `TAVILY_API_KEY` — Tier-1 search providers
- `WEB_RAG_ENABLED` — Enable embedding-based web RAG
- `MEDIUM_LONGCTX_CONTEXT` — Long context window size

**M4 Mac Optimization** (`src/config/settings.py`):
Activated via `MACHINE_TYPE=M4_MAC` or `OPTIMIZE_FOR_M4=true`. Reduces memory search window, adjusts timeouts, limits thread workers.

---

## 16. Test Suite

40+ test files in `tests/` using pytest + Hypothesis for property-based testing.

**Key Test Files:**

| File | Coverage |
|------|----------|
| `test_router_model_swap.py` | 38 tests: 13 correctness properties for model swap continuity |
| `test_router_properties.py` | Route domain, token budget, HITL threshold properties |
| `test_router_web_intent.py` | Web intent routing, vision detection, cloud escalation |
| `test_anonymization_properties.py` | PII detection round-trip properties |
| `test_conversation_continuity_properties.py` | State preservation across swaps |
| `test_swap_manager_properties.py` | Variant tracking, idempotence |
| `test_llm_pool_properties.py` | Caching, cloud unavailability |
| `test_toolbox_registry_properties.py` | Tool resolution, ask_user inclusion |
| `test_complex_node_properties.py` | Fallback chains, model selection |
| `test_skills.py` | Skill loading, matching, invocation |
| `test_graph.py` | LangGraph wiring, route_decision mapping |
| `test_notebook.py` | Stateful REPL execution |
| `test_todo.py` | Task tracking CRUD |
| `test_web_tools.py` | Search pipeline, bot detection |

**Running Tests:**
```bash
pytest tests/ -v --tb=short
pytest tests/test_router_model_swap.py -v  # Router swap tests only
```

**Configuration** (`pytest.ini`):
- `asyncio_mode = auto`
- Markers: `network`, `integration`, `llm`
- `norecursedirs = standalone .git __pycache__`

---

## 17. Project Structure

```
owlynn/
├── src/
│   ├── agent/                    # LangGraph orchestration
│   │   ├── graph.py              # Graph builder + init_agent
│   │   ├── state.py              # AgentState TypedDict
│   │   ├── llm.py                # LLMPool (3-slot pool)
│   │   ├── swap_manager.py       # M-tier model hot-swapping
│   │   ├── tool_sets.py          # Dynamic toolbox registry
│   │   ├── anonymization.py      # PII scrubbing for cloud
│   │   ├── response_styles.py    # Style hints for prompts
│   │   ├── lm_studio_compat.py   # Local server message formatting
│   │   ├── nodes/
│   │   │   ├── router.py         # 5-way routing + HITL
│   │   │   ├── simple.py         # Small LLM fast path
│   │   │   ├── complex.py        # Complex reasoning + fallbacks
│   │   │   ├── security_proxy.py # Tool execution governance
│   │   │   └── memory.py         # Memory inject + write
│   │   └── router/               # Enhanced router package
│   │       ├── models.py         # TaskFeatures, RouteClassification
│   │       ├── feature_extractor.py
│   │       ├── classifier.py     # RouteClassifier
│   │       ├── selector.py       # RouteSelector (swap-aware)
│   │       └── budget.py         # Token budget estimation
│   ├── api/
│   │   ├── server.py             # FastAPI + WebSocket
│   │   └── file_processor.py     # Background file watcher
│   ├── memory/
│   │   ├── user_profile.py       # User preferences
│   │   ├── persona.py            # Agent personality
│   │   ├── memory_manager.py     # Cross-session facts
│   │   ├── personal_assistant.py # Topics, interests, decay
│   │   ├── project.py            # Project management
│   │   └── long_term.py          # Mem0 + Qdrant
│   ├── tools/
│   │   ├── web_tools.py          # Search + fetch
│   │   ├── web_search_enhanced.py # SearXNG integration
│   │   ├── web_retrieval.py      # Embedding-based RAG
│   │   ├── core_tools.py         # File management + memory
│   │   ├── doc_generator.py      # DOCX/XLSX/PPTX/PDF
│   │   ├── notebook.py           # Stateful Python REPL
│   │   ├── todo.py               # Task tracking
│   │   ├── skills.py             # Skill templates
│   │   ├── ask_user.py           # HITL clarification
│   │   └── mcp_client.py         # MCP server integration
│   └── config/
│       └── settings.py           # Global config + M4 optimization
├── frontend/
│   ├── index.html                # Single-page app
│   ├── script.js                 # ~3000 lines of vanilla JS
│   ├── style.css                 # Custom dark theme
│   └── vendor/                   # Vendored: Tailwind, DOMPurify, Marked, Mammoth
├── skills/                       # 11 prompt templates (.md)
├── data/                         # User data (JSON files)
├── tests/                        # 40+ test files
├── docs/                         # Architecture + API docs
│   ├── HUMAN_PROJECT_GUIDE.md    # Entry point for developers
│   ├── AI_AGENT_PROJECT_GUIDE.md # Rules and expectations for AI agents
│   └── PROJECT_DOCUMENTATION.md  # Full architecture + status + roadmap
├── docker-compose.yml            # Redis + Qdrant + SearXNG
├── mcp_config.json               # MCP server config
├── requirements.txt              # Python dependencies
└── README.md                     # Quick start guide
```

---

## 18. Developer + AI Agent Documentation Map

Use this section to quickly find the right documentation surface by role.

### For Developers (Human)

- `README.md` — setup and startup flow
- `docs/HUMAN_PROJECT_GUIDE.md` — day-to-day workflow conventions
- `docs/ARCHITECTURE_OVERVIEW.md` — high-level architecture
- `docs/API_REFERENCE.md` — backend endpoint contract
- `docs/TOOLS.md` — available tool behaviors and constraints
- `docs/LINEAR_GITHUB_SYNC.md` + `docs/LINEAR_PROJECT_OVERSIGHT.md` — issue and project tracking process

### For AI Agents

- `docs/AI_AGENT_PROJECT_GUIDE.md` — mission, execution rules, testing policy
- `docs/AGENT_FLOW.md` — graph/node control flow
- `docs/CHAT_PROTOCOL.md` — websocket event contract
- `src/agent/` — routing, model selection, memory nodes, security proxy
- `src/tools/` — tool implementations exposed to the agent runtime

### Frontend Module Structure (Active)

`frontend/modules/` is now split into focused UI modules:
- `command-bar.js` — command palette and quick actions
- `context-health-bar.js` — context quality and capacity indicators
- `explorer.js` — workspace/project browsing interactions
- `knowledge-map.js` — relationship/navigation map UI
- `orchestrator-panel.js` — orchestration controls and status
- `project-vault.js` — project-level storage/views
- `stage.js` — staged action area and transitions
- `tool-dock.js` — tool quick-access and status
- `workspace-state.js` — workspace-level state management

---

## 19. Current Progress Snapshot

This snapshot reflects active implementation status in the current repository state.

### Completed / Stable

- Core LangGraph 7-node orchestration is in place with routing, tool loop, and memory writeback.
- Hybrid model strategy (small/medium/cloud) and medium-model swap flow are implemented.
- Security proxy and HITL approvals are integrated for sensitive operations.
- Memory stack (profile/persona/topics/interests/project context) is wired end-to-end.
- FastAPI + WebSocket backend and Tauri frontend shell are integrated.
- Property-based and regression-focused test suites are established across backend and frontend.

### In Progress

- Frontend migration from monolithic logic into modular `frontend/modules/*`.
- Expanded router package (`src/agent/router/*`) with structured feature extraction and budget logic.
- Additional summarize flow (`src/agent/nodes/summarize.py`) and graph wiring validation.
- New project/workspace state and multi-project chat persistence hardening.
- Contributor workflow/docs improvements (`CONTRIBUTING.md`, git hooks, Linear docs).

---

## 20. Current Bug Tracker

Known active bug themes being tracked in tests and audits:

1. **Workspace switching edge cases**
   - State bleed or stale UI references during workspace transitions.
   - Coverage targets: `frontend/tests/workspace-switching-*.test.js`, `tests/test_project_context_isolation_properties.py`.

2. **Frontend/backend contract mismatches**
   - Payload shape and event-order mismatches across websocket/API surfaces.
   - Coverage target: `tests/test_frontend_backend_alignment.py`.

3. **Cloud fallback and anonymization safety**
   - Ensure sensitive content remains protected when cloud fallback occurs.
   - Coverage target: `tests/test_cloud_fallback_anonymization_leak.py`.

4. **Router/model-selection regressions**
   - Route drift under long context, tools-needed prompts, or borderline complexity.
   - Coverage targets: `tests/test_router_model_swap.py`, `tests/test_router_properties.py`.

5. **CRUD + project-state consistency**
   - File/project operations require stronger invariants under concurrent or repeated actions.
   - Coverage targets: `tests/test_crud_operations.py`, `tests/test_crud_properties.py`, frontend CRUD property tests.

---

## 21. Future Plan

### Near-Term

- Finalize modular frontend stabilization and remove legacy duplicate logic.
- Close outstanding workspace/project-state regressions with deterministic integration tests.
- Complete summarize-node production wiring (routing policy + UI behavior + persistence).
- Tighten tool-awareness and tool-category selection behavior in complex agent paths.

### Mid-Term

- Introduce stronger observability for route decisions, fallback reasons, and tool execution outcomes.
- Expand API contract tests and snapshot tests for websocket event sequences.
- Improve project-scoped memory isolation and cross-project retrieval precision.
- Polish developer onboarding with a single bootstrap command and clearer troubleshooting docs.

### Long-Term

- Move toward multi-agent orchestration patterns with explicit planner/executor roles.
- Add richer multimodal context handling and safer cloud escalation policies.
- Strengthen offline-first reliability with graceful degradation for external dependencies.
- Build release automation (quality gates + changelog + versioned docs).

---

## 22. Roadmap

### Phase 1 — Stabilization (Now)

- Ship modular frontend architecture with parity to previous behavior.
- Resolve known workspace-switching and state-isolation regressions.
- Lock down anonymization + fallback safety through property tests.

### Phase 2 — Reliability & Visibility

- Add route/fallback telemetry and actionable debug surfaces.
- Harden API/WS contract guarantees and failure-handling UX.
- Standardize CI gates for critical property and integration suites.

### Phase 3 — Capability Expansion

- Expand summarize/context compression capabilities for long-running chats.
- Improve project vault + knowledge map for cross-session continuity.
- Introduce higher-level orchestration UX in the frontend.

### Phase 4 — Scale & Governance

- Formalize documentation versioning and architecture decision records.
- Add release train process linked to Linear milestones.
- Establish performance and memory SLOs for local-first operation.
