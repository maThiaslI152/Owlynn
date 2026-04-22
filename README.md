# Owlynn — Local AI Cowork Agent

A private, local-first AI productivity agent inspired by Anthropic's Cowork. Runs entirely on your machine with LangGraph orchestration, dual local LLMs, and a Cowork-style tool system.

## Quick Start

```bash
# 1. Start LM Studio with both models loaded (port 1234)
# 2. Start services + backend + desktop app:
./start.sh
```

## Architecture

- **Orchestrator**: LangGraph (stateful cyclic graph with 7 nodes)
- **Small Model**: Liquid LFM2.5-1.2B (routing + quick answers, ~700 tok/s)
- **Large Model**: Qwen3.5-9B (reasoning + tool calling, ~9 tok/s)
- **Backend**: FastAPI + WebSocket streaming
- **Frontend**: Tauri desktop app (offline-capable, vendored dependencies)
- **Search**: SearXNG (self-hosted) → DDG/Bing fallbacks
- **Memory**: Mem0 + ChromaDB + JSON files

## Tools (20)

| Category | Tools |
|----------|-------|
| Web | web_search, fetch_webpage |
| Files | read, write, edit, list, delete workspace files |
| Documents | create_docx, create_xlsx, create_pptx, create_pdf |
| Compute | notebook_run, notebook_reset |
| Memory | recall_memories |
| Tasks | todo_add, todo_list, todo_complete |
| Skills | list_skills, invoke_skill |
| HITL | ask_user (with choice buttons) |

## Skills (11)

Reusable prompt templates in `skills/`. Zero token cost until invoked.

| Skill | Triggers |
|-------|----------|
| Research Assistant | research, investigate |
| Document Summarizer | summarize, tldr |
| Morning Briefing | briefing, daily summary |
| Visual Comparison | compare, vs, chart |
| Data Visualization | graph, plot, histogram |
| Meeting Notes | meeting notes, action items |
| Email Drafter | draft email, compose |
| Report Generator | create report, weekly report |
| Presentation Builder | make slides, powerpoint |
| Content Rewriter | rewrite, polish, proofread |
| Brainstorm | brainstorm, ideas, what if |

## Prerequisites

- Python 3.12+
- LM Studio with both models loaded
- Podman (for ChromaDB, SearXNG containers)
- Rust & Cargo (for Tauri desktop app)

## Documentation

- [Architecture Overview](docs/ARCHITECTURE_OVERVIEW.md)
- [Agent Flow](docs/AGENT_FLOW.md)
- [Tools Reference](docs/TOOLS.md)
- [Chat Protocol](docs/CHAT_PROTOCOL.md)
- [API Reference](docs/API_REFERENCE.md)
- [Human Project Guide](docs/HUMAN_PROJECT_GUIDE.md)
- [AI Agent Project Guide](docs/AI_AGENT_PROJECT_GUIDE.md)

## Project Structure

```
src/agent/       LangGraph orchestration (graph, nodes, state, LLM pool)
src/api/         FastAPI backend (server, file processor)
src/memory/      Memory system (Mem0, profiles, topics, interests)
src/tools/       Tool implementations (web, files, docs, notebook, todo, skills)
src/config/      Settings and M4 optimization config
frontend/        HTML/CSS/JS + vendored dependencies
skills/          Reusable prompt templates (markdown)
data/            User data (profile, memories, todos, topics)
tests/           Test suite
docs/            Architecture and API documentation
```
