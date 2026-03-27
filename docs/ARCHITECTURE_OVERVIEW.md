# Architecture Overview

Owlynn is a local-first AI productivity agent built with **LangGraph** for orchestration and **FastAPI** for the backend. Optimized for Apple Silicon (M4 Air 24GB) with dual-LLM architecture.

## Core Components

### 1. Orchestrator (LangGraph)

```
memory_inject → router → simple → memory_write → END
                       → complex_llm ↔ security_proxy ↔ tool_action → memory_write → END
```

- **memory_inject**: Loads user profile, persona, topics, interests, and long-term memory context.
- **router**: LFM2.5-1.2B classifies as `simple` or `complex`. Keyword heuristics bypass LLM for obvious cases. Conversations with tool history stay on `complex`.
- **simple**: LFM2.5-1.2B gives short direct answers. No tools. Falls back to large model on failure.
- **complex_llm**: Qwen3.5-9B with 20 tools bound. Emits tool calls or direct answers.
- **security_proxy**: Gates sensitive tools (file write/edit/delete, notebook). Auto-approves safe tools.
- **tool_action**: Executes approved tool calls via ToolNode, loops back to complex_llm.
- **memory_write**: Extracts topics/interests, saves to Mem0/ChromaDB, invalidates cache.

### 2. Dual-LLM Architecture

| Model | Role | Size | Speed |
|-------|------|------|-------|
| LFM2.5-1.2B (GGUF Q4_K_M) | Routing, simple answers, chat titles | 730MB | ~700 tok/s prompt, ~110 tok/s gen |
| Qwen3.5-9B (GGUF Q6_K) | Complex reasoning, tool calling | 8.3GB | ~130 tok/s prompt, ~9 tok/s gen |

Both served via LM Studio on port 1234 (OpenAI-compatible API).

### 3. Tools (20 bound to LLM)

**Web**: web_search (SearXNG → DDG → Bing), fetch_webpage
**Files**: read, write, edit, list, delete workspace files
**Documents**: create_docx, create_xlsx, create_pptx, create_pdf
**Compute**: notebook_run, notebook_reset (in-process Python REPL)
**Memory**: recall_memories
**Tasks**: todo_add, todo_list, todo_complete
**Skills**: list_skills, invoke_skill (11 productivity templates)
**HITL**: ask_user (with choice buttons)

### 4. Skills System

Reusable prompt templates in `skills/*.md`. Zero token cost until invoked.
Triggers match user intent keywords. Currently: research, summarize, briefing,
comparison, visualization, meeting notes, email, report, presentation, rewriter, brainstorm.

### 5. Web Search Pipeline

```
Tier 0:   wttr.in (weather fast path)
Tier 0.5: SearXNG (self-hosted, localhost:8888)
Tier 1A:  Brave/Serper/Tavily APIs (if keys set)
Tier 1B:  curl_cffi (DDG/Bing HTML scraping)
Tier 2:   DDGS Python library / httpx fallbacks
Tier 3:   Playwright (full browser)
```

### 6. Memory System

- **Short-term**: LangGraph checkpointer (MemorySaver or Redis)
- **Long-term**: Mem0 + ChromaDB (multilingual-e5-small embeddings)
- **Data files**: JSON storage for topics, interests, conversations, todos

### 7. Frontend

- Tauri desktop app loading from FastAPI (http://127.0.0.1:8000)
- Vanilla HTML/JS/CSS with Tailwind utilities
- All dependencies vendored locally (offline-capable)
- WebSocket streaming for real-time responses
- Tool execution cards, ask-user with choice buttons, thinking suppression

### 8. Infrastructure

- **Docker Compose**: Redis, ChromaDB, SearXNG
- **LM Studio**: Local LLM inference server
- **No sandbox/container needed for tool execution** — all tools run natively
