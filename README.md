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
- Node.js (for Tauri CLI and MCP servers)
- Rust & Cargo (for Tauri Desktop App)
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

## Customization & Advanced Settings

### Settings Dashboard (NEW - Cowork-like Interface)

Click the **profile card** in the sidebar to open the advanced Settings modal with four tabs:

**📋 Profile Tab**
- Display name, language preference, response style
- LLM model URL and model name configuration
- Direct backend model selection

**⚙️ System Tab** (NEW)
- **Agent Persona**: Customize name and communication tone
- **System Prompt Editor**: Full control over agent behavior
- **Custom Instructions**: Add domain-specific rules and guidelines
- **Reset to Default**: Quick access to default configuration

**🧠 Memory Tab** (NEW)
- **Enable/Disable Short-term Memory**: Toggle conversation context retention
- **Enable/Disable Long-term Memory**: Toggle cross-session memory
- **Memory Manager**: Add facts agent remembers about you and your preferences
- **Memory Viewer**: See all stored memories with delete options

**🚀 Advanced Tab** (NEW)
- **Inference Parameters**:
  - Temperature (0.0-2.0): Control creativity vs focus
  - Top-p (0.0-1.0): Nucleus sampling for diversity
  - Max Tokens (256-8192): Response length limit
  - Top-k (0-100): Token selection diversity
- **Behavior Options**:
  - Streaming Responses: See output as it generates
  - Show Thinking: Display internal reasoning (if available)
  - Show Tool Execution: Visualize tool usage

### System Prompt Customization

Define how the agent behaves by editing the system prompt. Example:

```
You are Owlynn, a helpful AI assistant specialized in backend systems.
You excel at code review, architecture design, and system optimization.
Always explain your reasoning step-by-step. 
Prefer Python and Go for demonstrations.
Be direct and concise - the user values efficiency.
```

### Memory Management

Store facts for the agent to remember:
- "I'm a Rust developer"
- "I prefer minimal, readable code"
- "I work in distributed systems"
- "I like detailed performance analysis"

Agent will reference these in future conversations for personalized responses.

### Inference Tuning

Fine-tune model behavior for different tasks:

**For Coding**: Low temperature (0.2), high max_tokens (4096)  
**For Brainstorming**: High temperature (1.2), nucleus sampling 0.95  
**For Analysis**: Medium temperature (0.7), streaming enabled  
**For Summaries**: Low temperature (0.3), low max_tokens (1024)  

See [COWORK_FRONTEND_UPDATE.md](COWORK_FRONTEND_UPDATE.md) for detailed guide.

### Supported File Formats

The agent can automatically understand and process a wide variety of file formats. Files are automatically converted to readable text formats when uploaded:

**Document Formats:**
- PDF (`.pdf`) - Extracts text with page markers
- Microsoft Word (`.docx`) - Extracts paragraph text
- Markdown (`.md`, `.markdown`) - Passed through with validation

**Data & Serialization:**
- JSON (`.json`) - Pretty-printed with syntax highlighting
- XML (`.xml`) - Formatted with tree structure visualization
- YAML (`.yaml`, `.yml`) - Structured configuration display
- TOML (`.toml`) - Configuration format with schema preservation
- CSV/XLSX (`.csv`, `.xlsx`) - Converted to Markdown tables
- INI/CONF (`.ini`, `.conf`, `.config`) - Section-based parsing

**Web & Markup:**
- HTML (`.html`, `.htm`) - Extracts readable content and structure
- Databases (`.db`, `.sqlite`, `.sqlite3`) - Lists tables, columns, and sample data

**Archives:**
- ZIP (`.zip`) - Lists contents
- TAR/GZ (`.tar`, `.gz`) - Lists contents
- RAR/7Z (`.rar`, `.7z`) - Requires additional utilities

**Text & Code:**
- Source Code (`.py`, `.js`, `.ts`, `.java`, `.cpp`, `.c`, `.go`, `.rs`, `.rb`, `.php`) - Analyzed with metadata (line count, functions, classes)
- Log Files (`.log`) - Tails last 500 lines with formatting
- Plain Text (`.txt`) - Direct readability

**Auto-Processing:**
Files are automatically processed when uploaded and cached in `.processed/` directory for instant retrieval during conversations.

See [LIGHTPANDA_GUIDE.md](LIGHTPANDA_GUIDE.md) for detailed browser automation documentation.

## Enhanced Chat Experience

The chat interface now features:
- **Syntax Highlighting**: Beautiful highlighted code blocks for 190+ languages
- **Tool Execution Visibility**: Watch tools run with real-time status cards
- **Rich Formatting**: Tables, lists, and math equations render properly
- **Model Information**: See which model was used for each response
- **Error Cards**: Clear, formatted error messages with details
- **Copy & Regenerate**: Easy message management

See [IMPROVEMENTS.md](IMPROVEMENTS.md) for upgrade details.

