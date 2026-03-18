# Local Cowork Agent

A private, local-first autonomous agent based on Anthropic’s Cowork platform. This project uses LangGraph for orchestration, a local LLM (e.g., GLM-4 via MLX or Qwen via LM Studio) for multimodal and text reasoning, and a dual-memory system for robust context tracking.

## Core Architecture

- **Orchestrator:** LangGraph (Stateful, cyclic graph-based logic)
- **Brain:** Local LLM running via LLM Server (e.g., MLX or LM Studio)
- **Short-term Memory:** Redis (Thread-level checkpointer for LangGraph)
- **Long-term Memory:** ChromaDB + Mem0 (Cross-thread semantic retrieval)
- **Execution Sandbox:** Podman container with mounted workspace volume

## Prerequisites

- Python 3.12+
- Node.js (for some MCP servers if needed)
- Podman and `podman compose`
- Apple Silicon Mac (M-series) or suitable hardware for local inference

## Usage

### 1. Start Support Services
The agent requires Redis and ChromaDB.
```bash
podman compose up -d
```

### 2. Start LLM Server (Model Backend)
Before running the agent, start your local LLM server.

#### Option A: MLX VLM Server (for Apple Silicon)
```bash
./runmlx.sh
```
*Starts on `127.0.0.1:8080`.*

#### Option B: LM Studio (Alternative)
1. Load your model in LM Studio (e.g., `qwen/qwen3.5-9b`).
2. Enable the **Local Inference Server** in LM Studio (usually port `1234`).
3. Verify or update `data/user_profile.json` with your model name and port:
   ```json
   "llm_base_url": "http://127.0.0.1:1234/v1",
   "llm_model_name": "qwen/qwen3.5-9b"
   ```

### 3. Start Agent Backend & Frontend

#### Option A: Browser Web App
Run the FastAPI application:
```bash
./run.sh
```
*This starts the backend on `127.0.0.1:8000` and serves the frontend in your browser at [http://127.0.0.1:8000](http://127.0.0.1:8000).*

#### Option B: Tauri Desktop App
Run the integrated runner script:
```bash
chmod +x run_tauri.sh
./run_tauri.sh
```
*This starts the background FastAPI backend and then launches the native desktop window using Tauri.*


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
