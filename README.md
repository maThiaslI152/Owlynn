# Local Cowork Agent

A private, local-first autonomous agent based on Anthropic’s Cowork platform. This project uses LangGraph for orchestration, a local LLM (e.g., GLM-4 via MLX or Qwen via LM Studio) for multimodal and text reasoning, and a dual-memory system for robust context tracking.

## 📚 Documentation Index

For detailed guides and architecture, refer to the `docs/` folder:

### Contributor Start Here

If you are modifying code, use this order:

1. **[Architecture Overview](docs/ARCHITECTURE_OVERVIEW.md)** — high-level graph, memory, and backend layout.
2. **[Agent Flow](docs/AGENT_FLOW.md)** — exact node wiring and control flow used at runtime.
3. **[Chat & Events Protocol](docs/CHAT_PROTOCOL.md)** — frontend/backend WebSocket contract.
4. **[Tools & Tool Binding](docs/TOOLS.md)** — what tools the large model can actually call.
5. **[API Reference](docs/API_REFERENCE.md)** — REST endpoints and server entrypoints.
6. **[Extending the Agent](docs/EXTENDING_AGENT.md)** — safe change points and regression checklist.

*   **[Architecture Overview](docs/ARCHITECTURE_OVERVIEW.md)**: High-level system design and LangGraph flow describing current logic.
*   **[Chat & Events Protocol](docs/CHAT_PROTOCOL.md)**: WebSocket payload/event contract
*   **[Agent Flow](docs/AGENT_FLOW.md)**: Node-by-node LangGraph execution
*   **[Tools & Tool Binding](docs/TOOLS.md)**: Which tools are bound/executed in `complex`
*   **[API Reference](docs/API_REFERENCE.md)**: REST endpoints and WebSocket entrypoint
*   **[Extending the Agent](docs/EXTENDING_AGENT.md)**: Where to change routing/tools/memory safely
*   **Guides**:
    *   **[Quickstart](docs/guides/quickstart.md)**: Setup and run the application.
    *   **[Backend Integration](docs/guides/backend_integration.md)**: Details on tool execution events and WebSocket updates.
    *   **[Frontend Update](docs/guides/frontend_update.md)**: Details on the Cowork-style interface and setting options.
    *   **[LLM Chat Prompt Test](docs/guides/llm_chat_prompt_test.md)**: Manual verification prompts for routing, memory, and tool behavior.
    *   **[LM Studio / Qwen Jinja](docs/guides/lm_studio.md)**: Fixing “No user query found in messages” with local inference.
    *   **[File Formats](docs/guides/file_formats.md)**: Supported document types and processing.
    *   **[Browser Automation](docs/guides/lightpanda.md)**: setup and use Lightpanda for dynamic crawling.
    *   **[M4 Deployment](docs/guides/m4_deployment.md)**: Optimization strategies for Apple Silicon Macs.
    *   **[Personal Assistant Memory](docs/guides/personal_assistant_memory.md)**: Overview of topic/intensity tracking.
*   **Technical Notes**:
    *   [File Format Implementation](docs/technical/file_format_implementation.md)
    *   [LangGraph Optimization](docs/technical/langgraph_optimization.md)
    *   [Quick Reference](docs/technical/quick_reference.md)
*   **Archive**:
    *   [Implementation Checklist](docs/archive/implementation_checklist.md)
    *   [Verification Checklist](docs/archive/verification_checklist.md)

---

## Core Architecture


- **Orchestrator:** LangGraph (Stateful, cyclic graph-based logic)
- **Brain:** Local LLM running via LLM Server (e.g., MLX or LM Studio)
- **Short-term Memory:** LangGraph checkpointer (`MemorySaver` by default, best-effort `AsyncRedisSaver` fallback when Redis is available)
- **Long-term Memory:** Mem0 (personal assistant topic/interest extraction + enriched facts) and the local memory retrieval used by `memory_inject`
- **Execution Sandbox:** Podman container with mounted workspace volume

## Prerequisites

- Python 3.12+
- Node.js (for Tauri CLI and MCP servers)
- Rust & Cargo (for Tauri Desktop App)
- Podman and `podman compose`
- Apple Silicon Mac (M-series) or suitable hardware for local inference

## Usage

### 1. Start LLM Server (Model Backend)
Before running the agent, start your local LLM server.

#### LM Studio Setup
1. Load your model in LM Studio (e.g., `qwen/qwen3.5-9b` and `nemotron`).
2. Enable the **Local Inference Server** in LM Studio (usually port `1234`).
3. Verify or update `data/user_profile.json` with both model names:
   ```json
   "small_llm_base_url": "http://127.0.0.1:1234/v1",
   "small_llm_model_name": "nvidia/nemotron-3-nano-4b",
   "large_llm_base_url": "http://127.0.0.1:1234/v1",
   "large_llm_model_name": "qwen/qwen3.5-9b"
   ```

### 2. Start Application
To start the entire support stack (Redis, ChromaDB), Backend, and Frontend (Tauri Desktop Window), run:

```bash
chmod +x start.sh  # (First time only)
./start.sh
```

*This script will:*
1. Auto-start **Podman containers** for Redis and ChromaDB.
2. Verify **LM Studio** is active with your model loaded.
3. Launch the **FastAPI backend** asynchronously.
4. Open the native **Tauri desktop window**.

### 4. Access the UI
Open your browser and navigate to:
[http://127.0.0.1:8000](http://127.0.0.1:8000)

## Codebase Structure
- `src/agent/`: Core LangGraph agent logic and orchestration.
- `src/api/`: FastAPI backend serving requests to the agent.
- `src/memory/`: Memory management (long-term, user profiles, etc.).
- `src/tools/`: Custom tools available to the agent (sandbox, web, translation, **browser automation**).
- `frontend/`: Single-page app for chatting with the agent with **enhanced UI** (syntax highlighting, tool execution visibility).
- `assets/`: Media and icons for the application (e.g., app logos).
- `tests/`: Automated unit and integration tests.
  - `standalone/`: Subdirectory for standalone verification and utility scripts.

## Available Tools

### Core Tools
- **execute_sandboxed_shell**: Run bash commands in secure Podman sandbox
- **read/write_workspace_file**: File operations
- **execute_python_code**: Run Python directly
- **search_workspace_files**: Search file contents
- **web_search**: Metasearch across search engines
- **fetch_webpage**: Fetch pages (static HTTP)

### Browser Automation (Lightpanda)
- **lightpanda_fetch_page**: Render dynamic pages with JavaScript
- **lightpanda_execute_js**: Run custom JavaScript on pages  
- **lightpanda_screenshot**: Capture webpage screenshots
- **lightpanda_extract_data**: Scrape structured data with CSS selectors
- **lightpanda_health_check**: Verify Lightpanda installation

### Memory & Knowledge
- **remember_fact**: Store cross-session memories
- **recall_memories**: Search stored facts
- **update_persona**: Customize agent behavior

## ⚙️ Customization & Settings

Owlynn features a comprehensive settings dashboard with tabs for Profile, System Prompts, Memory Toggle, and Advanced Inference parameters.

For detailed information on configuring the agent, see:
*   **[Frontend Update & Settings Guide](docs/guides/frontend_update.md)**: Explains the tabbed interface, memory toggles, and inference tuning.

---

## 📄 Supported File Formats

The agent automatically processes uploaded files (PDF, Word, MarkDown, JSON, etc.) and caches them for instant retrieval.

For a full list of supported formats and processing details, see:
*   **[File Formats Guide](docs/guides/file_formats.md)**

---

## ✨ Enhanced Chat Experience

The interface supports syntax highlighting, tool execution status cards, rich formatting, and error displays.

For details on the upgrades, see the **[Frontend Update Guide](docs/guides/frontend_update.md)**.
For browser automation details, see **[Browser Automation (Lightpanda)](docs/guides/lightpanda.md)**.
