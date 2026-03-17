# Local Cowork Agent

A private, local-first autonomous agent based on Anthropic’s Cowork platform. This project uses LangGraph for orchestration, GLM-4.6V-Flash-4bit (via MLX) for multimodal reasoning, and a dual-memory system for robust context tracking.

## Core Architecture

- **Orchestrator:** LangGraph (Stateful, cyclic graph-based logic)
- **Brain:** GLM-4.6V-Flash-4bit running locally via MLX-LM
- **Short-term Memory:** Redis (Thread-level checkpointer for LangGraph)
- **Long-term Memory:** ChromaDB + Mem0 (Cross-thread semantic retrieval)
- **Execution Sandbox:** Podman container with mounted workspace volume

## Prerequisites

- Python 3.12+
- Node.js (for some MCP servers if needed)
- Podman and `podman compose`
- Apple Silicon Mac (M-series)

## Usage

### 1. Start Support Services
The agent requires Redis and ChromaDB.
```bash
podman compose up -d
```

### 2. Start MLX VLM Server (Model Backend)
Before running the agent, start the local LLM server:
```bash
./runmlx.sh
```
*This starts the model on `127.0.0.1:8080`.*

### 3. Start Agent Backend & Frontend
Run the FastAPI application:
```bash
./run.sh
```
*This starts the backend on `127.0.0.1:8000` and serves the frontend.*

### 4. Access the UI
Open your browser and navigate to:
[http://127.0.0.1:8000](http://127.0.0.1:8000)

## Codebase Structure
- `src/agent/`: Core LangGraph agent logic and orchestration.
- `src/api/`: FastAPI backend serving requests to the agent.
- `src/memory/`: Memory management (long-term, user profiles, etc.).
- `src/tools/`: Custom tools available to the agent (sandbox, web, translation).
- `frontend/`: Single-page app for chatting with the agent.
- `tests/`: Automated unit and integration tests.
