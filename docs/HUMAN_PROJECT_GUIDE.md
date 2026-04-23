# Owlynn Project Guide (Human)

## What Owlynn is

Owlynn is a local-first AI coworker that runs a LangGraph agent backend with a Tauri frontend.
It is designed to keep most reasoning and data on your machine while still supporting optional
cloud escalation and external tools (like Linear via MCP).

## Core architecture

- **Frontend**: Tauri + HTML/CSS/JS (`frontend/`)
- **Backend**: FastAPI + WebSocket streaming (`src/api/server.py`)
- **Agent orchestration**: LangGraph nodes (`src/agent/`)
- **Memory**: JSON + Mem0/Qdrant integrations (`src/memory/`)
- **Tools**: file ops, web, notebook, docs, skills, MCP (`src/tools/`)

## Main runtime flow

1. User message enters WebSocket chat endpoint.
2. Memory context is injected.
3. Router chooses simple vs complex model path.
4. Complex path may call tools through security proxy approval.
5. Response is streamed back and memory is updated.

## Current project priorities

- Stabilize hybrid model routing (small/medium/cloud DeepSeek pathing)
- Keep tool-call reliability high under local model edge cases
- Maintain clean project-level workflow through Linear (`WIN-`* issues)
- Improve startup and MCP resilience under flaky network conditions

## Local development checklist

1. Install Python dependencies: `pip install -r requirements.txt`
2. Start supporting services (Redis/Qdrant etc.)
3. Run backend: `python -m uvicorn src.api.server:app --host 0.0.0.0 --port 8000`
4. Run tests before merge:
  - Backend: `pytest tests/ -v`
  - Frontend: `cd frontend && npx vitest run`

## Delivery conventions

- Branch names include Linear key: `WIN-<id>-short-slug`
- PR title/body references the same issue key
- Keep feature changes scoped and test-backed
- Prefer focused PRs over large mixed commits

## Key docs

- `docs/ARCHITECTURE_OVERVIEW.md`
- `docs/AGENT_FLOW.md`
- `docs/TOOLS.md`
- `docs/API_REFERENCE.md`
- `docs/LINEAR_GITHUB_SYNC.md`
- `docs/LINEAR_PROJECT_OVERSIGHT.md`