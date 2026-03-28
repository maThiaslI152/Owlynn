# Requirements Document

## Introduction

Owlynn currently runs a dual-LLM architecture on a Mac M4 Air 24GB where a small model (LFM2.5-1.2B) handles routing and simple answers, and a large model (Qwen3.5-9B) handles complex reasoning. Both are served locally via LM Studio on port 1234.

This feature replaces the dual-LLM architecture with a three-tier S / M(swap) / L hybrid system designed around a hard VRAM constraint: the M4 24GB can only hold the S model + one M-tier model + embeddings in memory at any time. Additionally, the feature introduces Dynamic Tool Loading: instead of binding all 20 tools to the large model on every turn (~2000+ tokens of schema overhead), the Router classifies each request into a Toolbox category and the Complex_Node binds only the relevant subset of tools. The `ask_user` tool is always included as a HITL escape hatch. The tiers are:

- **S (Small) — Always loaded:** `liquid/lfm2.5-1.2b` stays resident in LM Studio memory at all times. Handles routing, simple answers, and chat title generation.
- **M (Medium) — Swappable local slot:** A single model slot in LM Studio that hot-swaps between three models based on task type:
  - `qwen/qwen3.5-9b` (DEFAULT) — general complex reasoning and tool calling
  - `zai-org/glm-4.6v-flash` (VISION) — when the user sends images or multimodal content
  - `LFM2 8B A1B GGUF Q8_0` (LONG CONTEXT) — when the task needs more context than Qwen's window but does not need cloud-level quality
  - Only ONE M-tier model is loaded at a time. Swapping uses LM Studio's native API (`POST /api/v1/models/load` and `POST /api/v1/models/unload`).
- **L (Large) — DeepSeek API (cloud):** `deepseek-chat` via the DeepSeek API. Used only when the task genuinely exceeds ALL local model capabilities — heavy frontier-quality reasoning, very large summarization, or when even the long-context local model is insufficient.

The router performs a two-stage decision: first simple vs complex, then for complex tasks it selects which M-tier variant to load (or escalates to cloud). The swap manager tracks which M-tier model is currently loaded and prefers the current model when the task is borderline, avoiding unnecessary swap latency. A working test for the LM Studio load/unload API already exists at `tests/standalone/test_lm_studio_model_load_unload.py`.

The Router also performs Toolbox Selection: it reads the user request and classifies it into one or more Toolbox categories (e.g., `web_search`, `file_ops`, `data_viz`, `productivity`, `memory`). The Complex_Node then binds only the tools from the selected Toolbox(es) plus the always-included `ask_user` tool, saving ~2000+ tokens of tool schema overhead per turn. If the Router is uncertain, it selects the `all` Toolbox to fall back to the current full-tool behavior.

When the Router's confidence in its routing or toolbox decision falls below a configurable threshold (default 0.6), it can use the `ask_user` tool via LangGraph's `interrupt()` mechanism to ask the user a short clarifying question before finalizing its decision. This HITL (Human-In-The-Loop) clarification resolves ambiguity at the cheapest point in the pipeline — before loading models or calling APIs. The feature is optional and can be disabled via User_Profile.

The system also replaces the in-memory `MemorySaver` checkpointer with a Redis-backed checkpointer (`langgraph-checkpoint-redis`) so that Short_Term_Memory (per-thread conversation history and graph state) persists across server restarts and is fully preserved when models swap mid-conversation. Redis runs as a container alongside ChromaDB and SearXNG in `docker-compose.yml`. Long_Term_Memory (Mem0/ChromaDB) and the memory injection/write pipeline are already model-agnostic — they operate on conversation content regardless of which LLM produced it — so conversation continuity across model swaps is achieved by persisting the checkpointer state in Redis while the memory nodes continue to enrich context from Mem0 on every turn.

The infrastructure layer also requires explicit Podman_Machine memory configuration to prevent container services from competing with LM Studio for the M4 Air's 24GB unified memory, along with Redis container provisioning in both `setup.sh` and `start.sh`. The existing test suite and documentation must be updated to cover the new architecture, including new test modules for the Swap_Manager, Anonymization_Engine, Toolbox_Registry, LLMPool, Redis checkpointing, and conversation continuity.

Additionally, the feature includes a Data Anonymization layer that protects sensitive user data when messages are sent to the Cloud_LLM (DeepSeek API). Before any message leaves the local machine, the Anonymization_Engine scans all content for PII and sensitive patterns (names, emails, phone numbers, file paths, API keys, IP addresses, and user-configurable terms), replaces each detected value with a deterministic placeholder (e.g., `[NAME_1]`, `[EMAIL_1]`), and maintains a per-request mapping table. After the Cloud_LLM responds, the De-anonymization step restores all placeholders back to their original values. This layer applies exclusively to the cloud path — local M-tier models are trusted since data never leaves the machine. The anonymization is toggleable via the `cloud_anonymization_enabled` field in User_Profile.

The frontend (vanilla HTML/JS/CSS with Tailwind utilities) must also be updated to reflect the S/M(swap)/L architecture. The Settings Modal Profile tab replaces the old "Large LLM" fields with Medium Models configuration and a Cloud (DeepSeek) section. The Advanced tab gains toggles for cloud escalation, anonymization, Router HITL, a clarification threshold slider, and custom sensitive terms. Model badges on AI messages use tier-specific colors (gray for small, blue for medium, purple for cloud, orange for fallback). Cloud token usage is displayed per-message and cumulatively via `/api/usage`. A swap indicator provides visual feedback during M-tier model loading, and the existing `handleAskUserInterrupt` mechanism handles Router clarification choices as clickable buttons.

## Glossary

- **LLMPool**: Singleton class in `src/agent/llm.py` that caches and provides `ChatOpenAI` instances for the Small_LLM, the currently-loaded Medium_LLM, and the Cloud_LLM
- **Small_LLM**: The local `liquid/lfm2.5-1.2b` model, always resident in LM Studio memory, used for routing, simple answers, and chat title generation
- **Medium_LLM**: The swappable local model slot; at any time holds exactly one of: Medium_Default, Medium_Vision, or Medium_LongCtx
- **Medium_Default**: The `qwen/qwen3.5-9b` model, the default M-tier variant for general complex reasoning and tool calling
- **Medium_Vision**: The `zai-org/glm-4.6v-flash` model, the M-tier variant for processing images and multimodal content
- **Medium_LongCtx**: The `LFM2 8B A1B GGUF Q8_0` model, the M-tier variant for tasks requiring a larger context window than Medium_Default provides
- **Cloud_LLM**: The DeepSeek API model (`deepseek-chat`) at `https://api.deepseek.com/v1`, used only when a task exceeds all local model capabilities
- **Swap_Manager**: A component that wraps the LM Studio native API for loading and unloading M-tier models, tracks the currently loaded variant, and handles swap latency
- **Router**: The node in the LangGraph that classifies user messages and selects the target model tier and variant
- **Route_Decision**: The routing outcome; one of `simple`, `complex-default`, `complex-vision`, `complex-longctx`, or `complex-cloud`
- **User_Profile**: JSON configuration file at `data/user_profile.json` storing LLM endpoints, model names, medium model variants, and user preferences
- **Settings_Module**: The `src/config/settings.py` module containing `M4_MAC_OPTIMIZATION` and global configuration constants
- **Agent_State**: The `AgentState` TypedDict that carries conversation state through the LangGraph, including `model_used`, `route`, `current_medium_model`, and `token_budget`
- **LM_Studio_Compat**: The compatibility layer in `src/agent/lm_studio_compat.py` that folds system messages into user messages for local LM Studio models
- **Complex_Node**: The `complex_llm_node` in `src/agent/nodes/complex.py` that performs reasoning with the selected M-tier model or Cloud_LLM and tool binding
- **LM_Studio_Native_API**: The LM Studio management API at `http://127.0.0.1:1234/api/v1/` providing model load, unload, and listing endpoints
- **Toolbox**: A named category of tools that can be selectively bound to the large model. Each Toolbox groups related tools by function domain (e.g., file operations, web search, document generation)
- **Toolbox_Registry**: A dictionary in `src/agent/tool_sets.py` that maps Toolbox names (`web_search`, `file_ops`, `data_viz`, `productivity`, `memory`) to their constituent tool lists
- **Selected_Toolboxes**: A list of Toolbox names stored in Agent_State that the Router chose for the current turn; the Complex_Node reads this field to determine which tools to bind
- **Always_Included_Tools**: Tools that are bound on every turn regardless of Toolbox selection; currently only `ask_user` (the HITL escape hatch)
- **Anonymization_Engine**: A module (`src/agent/anonymization.py`) that scans text for sensitive data patterns, replaces detected values with deterministic placeholders, and restores placeholders back to original values using a per-request mapping table
- **Anonymization_Mapping**: A per-request dictionary that maps placeholder tokens (e.g., `[NAME_1]`) to their original sensitive values (e.g., `"Tim"`); created fresh for each cloud request and not persisted
- **Placeholder_Token**: A deterministic replacement string in the format `[CATEGORY_N]` (e.g., `[NAME_1]`, `[EMAIL_1]`, `[PATH_1]`) used to substitute sensitive values before sending to the Cloud_LLM
- **Sensitive_Pattern**: A regex or lookup-based detection rule for a category of sensitive data (e.g., email addresses, phone numbers, API keys, file system paths, IP addresses)
- **De-anonymization**: The reverse process of scanning Cloud_LLM response text for Placeholder_Tokens and replacing them with the original values from the Anonymization_Mapping
- **Custom_Sensitive_Terms**: A user-configurable list of additional sensitive strings stored in User_Profile under the `custom_sensitive_terms` field, scanned alongside built-in Sensitive_Patterns
- **Router_Confidence**: A float value between 0.0 and 1.0 output by the Router alongside its routing and toolbox decisions, representing how certain the Router is about its classification
- **Router_Clarification_Threshold**: A configurable float value (default 0.6) stored in User_Profile under `router_clarification_threshold`; when Router_Confidence falls below this threshold, the Router may invoke the `ask_user` tool to request clarification from the user
- **Router_HITL_Mode**: A configurable boolean field in User_Profile (`router_hitl_enabled`, default `true`) that controls whether the Router is allowed to pause for user clarification; when `false`, the Router falls back to its best guess without asking
- **Redis_Checkpointer**: A Redis-backed implementation of the LangGraph checkpointer (`langgraph-checkpoint-redis`) that persists conversation state (messages, routing metadata, tool call history) to a Redis instance, replacing the in-memory `MemorySaver`
- **Short_Term_Memory**: The per-thread conversation history and graph state managed by the LangGraph checkpointer; distinct from Long_Term_Memory (Mem0/ChromaDB) which stores cross-session facts
- **Long_Term_Memory**: The cross-session factual memory managed by Mem0 and ChromaDB, storing user facts, topics, and interests that persist indefinitely across all threads
- **Thread_ID**: A unique string identifier for each conversation thread, used as the key for checkpointer state isolation; each thread maintains its own independent message history and graph state
- **Model_Swap_Continuity**: The property that conversation history and context are fully preserved when the active LLM changes mid-conversation (e.g., from Medium_Default to Medium_Vision and back), enabled by the checkpointer persisting all state independently of which model processes each turn
- **Test_Suite**: The collection of pytest test modules in the `tests/` directory that verify routing, graph compilation, tool behavior, memory, and integration correctness
- **Standalone_Tests**: Test scripts in `tests/standalone/` that run outside pytest and require live external services (e.g., LM Studio, Redis) to execute
- **Documentation_Set**: The collection of Markdown files in the `docs/` directory that describe the system architecture, API, agent flow, tools, and setup guides
- **Podman_Machine**: The Linux virtual machine managed by Podman on macOS that hosts all OCI containers (ChromaDB, SearXNG, Redis); its memory allocation directly competes with LM Studio and the Python backend for the M4 Air's 24GB unified memory
- **Settings_Modal**: The modal dialog in `frontend/index.html` containing Profile, System, Memory, and Advanced tabs for configuring Owlynn's behavior and LLM endpoints
- **Model_Badge**: A small pill-shaped UI element displayed on each AI message in the chat view, showing which model tier and variant produced the response (e.g., `"small-local"`, `"medium-default"`, `"large-cloud"`)
- **Model_Badge_Tier_Color**: A visual color scheme applied to the Model_Badge based on the model tier: gray for `small-local`, blue for `medium-*` variants, purple for `large-cloud`, and orange for fallback variants
- **Cloud_Token_Indicator**: A small UI element displayed near the Model_Badge when the Cloud_LLM was used, showing `prompt_tokens` and `completion_tokens` consumed for that response
- **Model_Swap_Indicator**: A transient status message (e.g., "Switching to vision model...") displayed in the chat view when the Swap_Manager is loading a new M-tier model, providing visual feedback during the swap latency period
- **Router_Clarification_UI**: The frontend handling of Router HITL clarification requests, presenting routing choices as clickable buttons (e.g., "Search the web", "Work with files", "Use cloud model") via the existing `handleAskUserInterrupt` mechanism

## Requirements

### Requirement 1: DeepSeek API Key Management

**User Story:** As a developer, I want to securely configure my DeepSeek API key, so that Owlynn can authenticate with the DeepSeek API when cloud escalation is needed.

#### Acceptance Criteria

1. WHEN the LLMPool initializes the Cloud_LLM, THE LLMPool SHALL read the DeepSeek API key from the `DEEPSEEK_API_KEY` environment variable first, then fall back to the `deepseek_api_key` field in User_Profile
2. IF the DeepSeek API key is not found in either the environment variable or User_Profile, THEN THE LLMPool SHALL log a warning and disable cloud escalation (all local M-tier models remain fully functional)
3. THE LLMPool SHALL treat the API key as a secret and not log its value at any log level
4. WHEN the User_Profile is updated with a new `deepseek_api_key` value via the REST API, THE LLMPool SHALL clear its cached Cloud_LLM instance so the next request uses the updated key

### Requirement 2: Four-Tier LLMPool (S / M-default / M-vision / M-longctx / L-cloud)

**User Story:** As a developer, I want the LLMPool to manage the Small_LLM (always loaded), a swappable Medium_LLM slot, and the Cloud_LLM, so that the system can route tasks to the appropriate model tier and variant.

#### Acceptance Criteria

1. THE LLMPool SHALL maintain three cached instance slots: `_small_llm` (always loaded Small_LLM), `_medium_llm` (the currently-loaded M-tier `ChatOpenAI` instance), and `_cloud_llm` (DeepSeek API)
2. THE LLMPool SHALL track the currently loaded M-tier variant in a `_current_medium_variant` field with possible values `"default"`, `"vision"`, `"longctx"`, or `None` (no M model loaded)
3. THE LLMPool SHALL expose a `get_medium_llm(variant: str)` async method that accepts `"default"`, `"vision"`, or `"longctx"` as the variant parameter
4. WHEN `get_medium_llm(variant)` is called and `_current_medium_variant` matches the requested variant, THE LLMPool SHALL return the cached `_medium_llm` instance without triggering a model swap
5. WHEN `get_medium_llm(variant)` is called and `_current_medium_variant` does not match the requested variant, THE LLMPool SHALL invoke the Swap_Manager to unload the current M-tier model and load the requested variant before returning the new `ChatOpenAI` instance
6. THE LLMPool SHALL create the Cloud_LLM as a `ChatOpenAI` instance with `base_url` from `cloud_llm_base_url` in User_Profile (defaulting to `https://api.deepseek.com/v1`), `model` from `cloud_llm_model_name` (defaulting to `deepseek-chat`), `streaming` set to `True`, and the resolved DeepSeek API key
7. THE LLMPool SHALL configure the Cloud_LLM with a default `max_tokens` of 8192 and a `temperature` of 0.4, and SHALL omit the `extra_body` parameter containing `max_output_tokens` to avoid incompatibility with the DeepSeek API
8. WHEN `get_cloud_llm()` is called and no valid API key is configured, THE LLMPool SHALL raise a descriptive error indicating cloud escalation is unavailable
9. WHEN `LLMPool.clear()` is called, THE LLMPool SHALL reset all cached instances (`_small_llm`, `_medium_llm`, `_cloud_llm`) and set `_current_medium_variant` to `None`

### Requirement 3: LM Studio Model Swap Manager

**User Story:** As a developer, I want a Swap_Manager component that wraps the LM Studio native API for model load/unload, so that the system can hot-swap M-tier models reliably with proper error handling.

#### Acceptance Criteria

1. THE Swap_Manager SHALL expose an async method `swap_model(target_variant: str)` that accepts `"default"`, `"vision"`, or `"longctx"` and loads the corresponding model key from the medium_models configuration in User_Profile
2. WHEN `swap_model` is called, THE Swap_Manager SHALL first unload the currently loaded M-tier model by sending `POST /api/v1/models/unload` with the `instance_id` of the current model, then load the target model by sending `POST /api/v1/models/load` with `{"model": target_model_key}`
3. THE Swap_Manager SHALL determine the `instance_id` of the currently loaded M-tier model by querying `GET /api/v1/models` and inspecting the `loaded_instances` array for the current model key
4. WHEN loading a model, THE Swap_Manager SHALL poll `GET /api/v1/models` until the target model appears in `loaded_instances`, with a configurable timeout defaulting to 120 seconds
5. IF the unload request fails, THEN THE Swap_Manager SHALL log a warning and proceed with the load attempt (LM Studio may handle the conflict)
6. IF the load request fails or the model does not appear in `loaded_instances` within the timeout, THEN THE Swap_Manager SHALL raise a `ModelSwapError` exception with a descriptive message including the target model key and the timeout duration
7. THE Swap_Manager SHALL expose a `get_current_variant() -> str | None` method that returns the currently loaded M-tier variant name or `None` if no M model is loaded
8. THE Swap_Manager SHALL expose a `get_loaded_instance_ids(model_key: str) -> list[str]` method that queries the LM Studio native API and returns instance IDs for the specified model
9. THE Swap_Manager SHALL use `httpx.AsyncClient` for all HTTP requests to the LM Studio native API at the base URL from User_Profile (defaulting to `http://127.0.0.1:1234`)

### Requirement 4: Smart Routing (Simple / Complex with Model Selection)

**User Story:** As a developer, I want the router to classify messages as simple or complex, and for complex messages to select the appropriate M-tier variant or cloud escalation, so that each task uses the optimal model while minimizing unnecessary model swaps.

#### Acceptance Criteria

1. THE Router SHALL classify each user message into one of five routes: `simple`, `complex-default`, `complex-vision`, `complex-longctx`, or `complex-cloud`
2. THE Router SHALL perform a two-stage decision: first classify as `simple` vs `complex` using existing keyword heuristics and Small_LLM classification, then for complex messages select the target model variant
3. WHEN the user message contains image attachments or multimodal content blocks (content list with `image_url` type entries), THE Router SHALL route to `complex-vision`
4. WHEN the estimated input token count exceeds 80% of the Medium_Default context window (accounting for system prompt and memory context) but fits within the Medium_LongCtx context window, THE Router SHALL route to `complex-longctx`
5. WHEN the estimated input token count exceeds the Medium_LongCtx context window, or the user message contains indicators of heavy mathematical computation, multi-step symbolic reasoning, or tasks explicitly requesting frontier-quality output, THE Router SHALL route to `complex-cloud`
6. THE Router SHALL route to `complex-default` as the fallback for all complex tasks that do not meet the criteria for vision, long-context, or cloud escalation
7. WHEN the requested route maps to the same M-tier variant that is currently loaded (as reported by the Swap_Manager), THE Router SHALL prefer that route over a marginally better alternative to avoid unnecessary swap latency
8. IF no valid DeepSeek API key is configured, THEN THE Router SHALL route all cloud-eligible tasks to `complex-default` or `complex-longctx` based on context size
9. THE Router SHALL log the routing decision, the selected variant, and the reason for the selection

### Requirement 5: Token Budget — Per Model Tier

**User Story:** As a developer, I want the router and complex node to use different context window budgets for each M-tier variant and the cloud path, so that token budgeting matches each model's actual capacity.

#### Acceptance Criteria

1. THE Router SHALL use a `_MEDIUM_DEFAULT_CONTEXT` value of 100000 to reflect the Medium_Default (Qwen3.5-9B) context window as configured in LM Studio
2. THE Router SHALL use a `_MEDIUM_LONGCTX_CONTEXT` value matching the Medium_LongCtx model's actual context window (configurable in Settings_Module, default 131072)
3. THE Router SHALL use a `_CLOUD_CONTEXT` value of 131072 (128K) to reflect the DeepSeek model context window
4. WHEN the Router selects a `complex-default` route, THE Router SHALL compute the token budget using `_MEDIUM_DEFAULT_CONTEXT` with `_LARGE_INPUT_RESERVE` of 4000
5. WHEN the Router selects a `complex-longctx` route, THE Router SHALL compute the token budget using `_MEDIUM_LONGCTX_CONTEXT` with `_LONGCTX_INPUT_RESERVE` of 4000
6. WHEN the Router selects a `complex-cloud` route, THE Router SHALL compute the token budget using `_CLOUD_CONTEXT` with `_CLOUD_INPUT_RESERVE` of 8000 to account for larger system prompts enabled by the expanded context window
7. THE Router SHALL set `_BUDGET_MAX` to 8192 for `complex-default`, 8192 for `complex-longctx`, and 16384 for `complex-cloud` routes
8. THE Complex_Node SHALL read the route from Agent_State to determine which context window constant to use for output budget capping

### Requirement 6: Complex Node Model Selection

**User Story:** As a developer, I want the complex node to select and invoke the correct model based on the router's decision, triggering M-tier swaps when needed and falling back gracefully on swap failure.

#### Acceptance Criteria

1. WHEN the Agent_State `route` is `complex-default`, THE Complex_Node SHALL invoke `LLMPool.get_medium_llm("default")` to obtain the Medium_Default model
2. WHEN the Agent_State `route` is `complex-vision`, THE Complex_Node SHALL invoke `LLMPool.get_medium_llm("vision")` to obtain the Medium_Vision model
3. WHEN the Agent_State `route` is `complex-longctx`, THE Complex_Node SHALL invoke `LLMPool.get_medium_llm("longctx")` to obtain the Medium_LongCtx model
4. WHEN the Agent_State `route` is `complex-cloud`, THE Complex_Node SHALL invoke `LLMPool.get_cloud_llm()` to obtain the Cloud_LLM
5. WHEN using the Cloud_LLM, THE Complex_Node SHALL send messages in standard OpenAI format with a separate system message (not folded into the first user message)
6. WHEN using any M-tier model, THE Complex_Node SHALL continue to use the LM_Studio_Compat folding behavior
7. IF `LLMPool.get_medium_llm(variant)` raises a `ModelSwapError`, THEN THE Complex_Node SHALL fall back to the currently loaded M-tier variant and log a warning indicating the swap failed
8. THE Complex_Node SHALL pass the route-appropriate token budget from Agent_State to the selected model

### Requirement 7: API Error Handling with Tiered Fallback

**User Story:** As a user, I want Owlynn to fall back gracefully through the model tiers when a model fails, so that I always get a response.

#### Acceptance Criteria

1. IF the Cloud_LLM request fails for any reason (network error, timeout, HTTP 4xx, HTTP 5xx), THEN THE Complex_Node SHALL retry the request once using `LLMPool.get_medium_llm("default")` (Medium_Default)
2. IF the Medium_Vision model request fails, THEN THE Complex_Node SHALL fall back to `LLMPool.get_medium_llm("default")` (Medium_Default) and log a warning
3. IF the Medium_LongCtx model request fails, THEN THE Complex_Node SHALL first attempt the Cloud_LLM, then fall back to `LLMPool.get_medium_llm("default")` with truncated context if cloud is also unavailable
4. WHEN falling back to a different model, THE Complex_Node SHALL apply the appropriate message format (LM_Studio_Compat folding for local models, standard OpenAI format for cloud) and use the fallback model's context window budget
5. WHEN falling back from any model, THE Complex_Node SHALL set `model_used` in Agent_State to a descriptive fallback value (e.g., `"medium-default-fallback"`, `"large-cloud-fallback"`) and log a warning
6. IF the Cloud_LLM returns an HTTP 401 or 403 (authentication) error, THEN THE Complex_Node SHALL append a note to the response indicating the user should check the DeepSeek API key configuration
7. THE Settings_Module SHALL set `M4_MAC_OPTIMIZATION["large_model"]["cloud_timeout"]` to 180 seconds to accommodate cloud API latency

### Requirement 8: Streaming Support

**User Story:** As a user, I want to see responses stream in real-time from both local and cloud models, so that I do not have to wait for the full response before seeing output.

#### Acceptance Criteria

1. THE Cloud_LLM ChatOpenAI instance SHALL have `streaming` set to `True` by default
2. THE Medium_LLM ChatOpenAI instances for all M-tier variants SHALL support streaming as configured by LM Studio
3. WHEN the WebSocket handler streams tokens from the Complex_Node, THE Server SHALL forward each token chunk to the frontend as it arrives, regardless of whether the source is a local M-tier model or the Cloud_LLM
4. WHILE streaming a response from the Cloud_LLM, THE Complex_Node SHALL handle connection interruptions by returning the partial content received so far as the response

### Requirement 9: LM Studio Compatibility

**User Story:** As a developer, I want the system prompt folding logic to apply to all local models and be skipped for the cloud model, so that each model receives messages in its expected format.

#### Acceptance Criteria

1. WHEN the target LLM base URL does not contain `127.0.0.1` or `localhost`, THE Complex_Node SHALL send messages in standard OpenAI format with a separate system message
2. THE Small_LLM and all M-tier model variants SHALL continue to use the LM_Studio_Compat folding behavior
3. THE LM_Studio_Compat module SHALL expose a function `is_local_server(base_url: str) -> bool` that determines whether a given base URL is a local LM Studio server

### Requirement 10: User Profile Updates for S/M/L Architecture

**User Story:** As a developer, I want the User_Profile to include configuration for all model tiers and M-tier variants, so that users can customize endpoints, model names, and variant mappings.

#### Acceptance Criteria

1. THE User_Profile SHALL include `cloud_llm_base_url` defaulting to `https://api.deepseek.com/v1`
2. THE User_Profile SHALL include `cloud_llm_model_name` defaulting to `deepseek-chat`
3. THE User_Profile SHALL include a `deepseek_api_key` field defaulting to an empty string
4. THE User_Profile SHALL include a `medium_models` object with three keys: `default` (defaulting to `"qwen/qwen3.5-9b"`), `vision` (defaulting to `"zai-org/glm-4.6v-flash"`), and `longctx` (defaulting to `"LFM2 8B A1B GGUF Q8_0"`)
5. THE User_Profile SHALL retain `small_llm_base_url` and `small_llm_model_name` for the Small_LLM configuration
6. THE User_Profile SHALL include a `cloud_escalation_enabled` boolean field defaulting to `true`, allowing users to disable cloud escalation entirely

### Requirement 11: Model Provenance in Agent State

**User Story:** As a user, I want to know which specific model produced each response, so that I can understand the source and quality tier of each answer.

#### Acceptance Criteria

1. WHEN the Complex_Node generates a response using Medium_Default, THE Complex_Node SHALL set `model_used` in Agent_State to `"medium-default"`
2. WHEN the Complex_Node generates a response using Medium_Vision, THE Complex_Node SHALL set `model_used` in Agent_State to `"medium-vision"`
3. WHEN the Complex_Node generates a response using Medium_LongCtx, THE Complex_Node SHALL set `model_used` in Agent_State to `"medium-longctx"`
4. WHEN the Complex_Node generates a response using the Cloud_LLM, THE Complex_Node SHALL set `model_used` in Agent_State to `"large-cloud"`
5. WHEN the Simple_Node generates a response, THE Simple_Node SHALL set `model_used` in Agent_State to `"small-local"`
6. WHEN any fallback occurs, THE Complex_Node SHALL set `model_used` to a descriptive fallback variant (e.g., `"medium-default-fallback"`, `"large-cloud-fallback"`)
7. THE Server SHALL include the `model_used` value in WebSocket response messages so the frontend can display the model source

### Requirement 12: Cost Awareness

**User Story:** As a user, I want visibility into my DeepSeek API token usage, so that I can monitor costs associated with cloud model usage.

#### Acceptance Criteria

1. WHEN the DeepSeek API returns usage metadata in the response, THE Complex_Node SHALL extract `prompt_tokens` and `completion_tokens` from the response
2. THE Agent_State SHALL include `api_tokens_used` as an optional field to carry token usage data through the graph
3. THE Server SHALL include token usage counts in WebSocket response messages when available
4. THE Server SHALL expose a `GET /api/usage` endpoint that returns cumulative token usage for the current session

### Requirement 13: Graph Flow Update

**User Story:** As a developer, I want the LangGraph to support the expanded routing decisions, so that the correct node and model handle each request.

#### Acceptance Criteria

1. THE `route_decision` function in `graph.py` SHALL accept five valid route values: `simple`, `complex-default`, `complex-vision`, `complex-longctx`, and `complex-cloud`
2. WHEN the route is `complex-default`, `complex-vision`, `complex-longctx`, or `complex-cloud`, THE graph SHALL direct to the `complex_llm` node (the Complex_Node reads the route from Agent_State to select the model and variant)
3. THE `route_decision` function SHALL default to `complex-default` for any unrecognized route value
4. THE Agent_State SHALL include a `route` field that accepts `"simple"`, `"complex-default"`, `"complex-vision"`, `"complex-longctx"`, or `"complex-cloud"` as valid values

### Requirement 14: Agent State Updates

**User Story:** As a developer, I want the Agent_State to carry the expanded routing and model tracking fields, so that all nodes in the graph can access the current model tier and variant information.

#### Acceptance Criteria

1. THE Agent_State SHALL include a `current_medium_model` field of type `str | None` that records which M-tier variant is currently loaded in LM Studio (values: `"default"`, `"vision"`, `"longctx"`, or `None`)
2. THE Agent_State SHALL include a `route` field that accepts the expanded route values: `"simple"`, `"complex-default"`, `"complex-vision"`, `"complex-longctx"`, or `"complex-cloud"`
3. THE Agent_State SHALL include a `model_used` field that accepts the expanded provenance values: `"small-local"`, `"medium-default"`, `"medium-vision"`, `"medium-longctx"`, `"large-cloud"`, and fallback variants
4. THE Agent_State SHALL include an `api_tokens_used` optional field of type `dict | None` to carry cloud API token usage data

### Requirement 15: Tool Categorization

**User Story:** As a developer, I want tools organized into named Toolbox categories in `tool_sets.py`, so that the system can selectively bind only the relevant tools for each request instead of all 20 tools.

#### Acceptance Criteria

1. THE Toolbox_Registry SHALL define a `web_search` Toolbox containing the `web_search` and `fetch_webpage` tools
2. THE Toolbox_Registry SHALL define a `file_ops` Toolbox containing the `read_workspace_file`, `write_workspace_file`, `edit_workspace_file`, `list_workspace_files`, and `delete_workspace_file` tools
3. THE Toolbox_Registry SHALL define a `data_viz` Toolbox containing the `create_docx`, `create_xlsx`, `create_pptx`, `create_pdf`, `notebook_run`, and `notebook_reset` tools
4. THE Toolbox_Registry SHALL define a `productivity` Toolbox containing the `todo_add`, `todo_list`, `todo_complete`, `list_skills`, and `invoke_skill` tools
5. THE Toolbox_Registry SHALL define a `memory` Toolbox containing the `recall_memories` tool
6. THE Toolbox_Registry SHALL be implemented as a Python dictionary mapping Toolbox name strings to lists of tool objects in `src/agent/tool_sets.py`
7. THE Toolbox_Registry SHALL expose a `resolve_tools(toolbox_names: list[str], web_search_enabled: bool) -> list` function that accepts a list of Toolbox names and returns the union of their tool lists plus the Always_Included_Tools
8. WHEN the `resolve_tools` function receives `"all"` in the `toolbox_names` list, THE function SHALL return the full tool set equivalent to the current `COMPLEX_TOOLS_WITH_WEB` or `COMPLEX_TOOLS_NO_WEB` depending on the `web_search_enabled` parameter
9. WHEN the `web_search_enabled` parameter is `False`, THE `resolve_tools` function SHALL exclude the `web_search` Toolbox tools from the result even if `web_search` is in the requested `toolbox_names`
10. THE `ask_user` tool SHALL be included in the result of `resolve_tools` regardless of which Toolbox names are requested

### Requirement 16: Router Toolbox Selection

**User Story:** As a developer, I want the Router to output a Toolbox selection alongside its routing decision, so that the Complex_Node knows which subset of tools to bind for each turn.

#### Acceptance Criteria

1. THE Router SHALL extend its output JSON to include a `toolbox` field alongside the existing `routing` and `confidence` fields, with format: `{"routing": "simple"|"complex", "confidence": 0.0-1.0, "toolbox": "toolbox_name"|["toolbox_name1", "toolbox_name2"]}`
2. WHEN the Router classifies a message as `simple`, THE Router SHALL set the `toolbox` field to an empty list (simple path does not use tools)
3. WHEN the user message involves web lookup, live data, or current information, THE Router SHALL include `"web_search"` in the `toolbox` selection
4. WHEN the user message involves reading, writing, editing, listing, or deleting workspace files, THE Router SHALL include `"file_ops"` in the `toolbox` selection
5. WHEN the user message involves creating documents, spreadsheets, presentations, PDFs, running code, data analysis, charts, or visualizations, THE Router SHALL include `"data_viz"` in the `toolbox` selection
6. WHEN the user message involves task management, skills, or workflow templates, THE Router SHALL include `"productivity"` in the `toolbox` selection
7. WHEN the user message involves recalling past conversations, user preferences, or stored facts, THE Router SHALL include `"memory"` in the `toolbox` selection
8. WHEN the user message contains multiple intents spanning different Toolbox categories, THE Router SHALL include all relevant Toolbox names in the `toolbox` list
9. IF the Router cannot confidently determine the Toolbox category, THEN THE Router SHALL set the `toolbox` field to `"all"` to fall back to the full tool set
10. THE Router prompt SHALL be updated to include Toolbox classification instructions and the list of valid Toolbox names: `web_search`, `file_ops`, `data_viz`, `productivity`, `memory`, `all`
11. THE Router SHALL store the selected Toolbox names in the `selected_toolboxes` field of Agent_State

### Requirement 17: Dynamic Tool Binding in Complex Node

**User Story:** As a developer, I want the Complex_Node to read the selected Toolbox from Agent_State and bind only those tools to the large model, so that tool schema overhead is reduced from ~2000+ tokens to only the relevant subset.

#### Acceptance Criteria

1. WHEN the Complex_Node prepares the large model for a turn, THE Complex_Node SHALL read the `selected_toolboxes` field from Agent_State
2. WHEN `selected_toolboxes` contains specific Toolbox names, THE Complex_Node SHALL call `resolve_tools(selected_toolboxes, web_search_enabled)` from the Toolbox_Registry to obtain the tool list
3. WHEN `selected_toolboxes` is empty, `None`, or contains `"all"`, THE Complex_Node SHALL fall back to the full tool set (`COMPLEX_TOOLS_WITH_WEB` or `COMPLEX_TOOLS_NO_WEB`)
4. THE Complex_Node SHALL bind the resolved tool list to the large model via `.bind_tools(resolved_tools)` instead of the current static `COMPLEX_TOOLS_WITH_WEB` or `COMPLEX_TOOLS_NO_WEB`
5. THE Complex_Node SHALL use the same resolved tool list when constructing the `ToolNode` for `complex_tool_action_node`
6. THE Complex_Node SHALL update the system prompt tool guidance section to list only the tools from the resolved Toolbox(es) instead of the full tool inventory
7. WHEN the conversation has tool history from a previous turn that used a different Toolbox, THE Complex_Node SHALL include those previously-used tools in the current tool binding to ensure `ToolMessage` references remain valid

### Requirement 18: Agent State for Toolbox Selection

**User Story:** As a developer, I want the Agent_State to carry the selected Toolbox names through the LangGraph, so that the Complex_Node can access the Router's Toolbox decision.

#### Acceptance Criteria

1. THE Agent_State SHALL include a `selected_toolboxes` field of type `list[str] | None` that carries the Toolbox names selected by the Router for the current turn
2. WHEN the Router sets `selected_toolboxes`, THE Agent_State SHALL accept a list of valid Toolbox names: `"web_search"`, `"file_ops"`, `"data_viz"`, `"productivity"`, `"memory"`, or `"all"`
3. THE `selected_toolboxes` field SHALL default to `None`, which the Complex_Node interprets as equivalent to `["all"]` (full tool set fallback)
4. THE Router SHALL set `selected_toolboxes` in its return dictionary alongside `route` and `token_budget`

### Requirement 19: Data Anonymization Engine

**User Story:** As a user, I want my sensitive data to be automatically anonymized before being sent to the DeepSeek cloud API, so that my personal information is protected when leaving my local machine.

#### Acceptance Criteria

1. THE Anonymization_Engine SHALL expose an `anonymize(text: str, context: dict) -> tuple[str, dict]` function that scans the input text for all registered Sensitive_Patterns, replaces each detected value with a Placeholder_Token, and returns the anonymized text along with the Anonymization_Mapping
2. THE Anonymization_Engine SHALL expose a `deanonymize(text: str, mapping: dict) -> str` function that scans the input text for all Placeholder_Tokens present in the Anonymization_Mapping and replaces each with its original value
3. THE Anonymization_Engine SHALL generate Placeholder_Tokens in the format `[CATEGORY_N]` where `CATEGORY` is an uppercase category name (e.g., `NAME`, `EMAIL`, `PHONE`, `PATH`, `API_KEY`, `IP`, `URL`, `CUSTOM`) and `N` is a sequential integer starting from 1 within each category
4. WHEN the same sensitive value appears multiple times in the input text, THE Anonymization_Engine SHALL use the same Placeholder_Token for all occurrences (deterministic within a single request)
5. THE Anonymization_Mapping SHALL be created fresh for each cloud request and not persisted to disk or shared across requests
6. THE Anonymization_Engine SHALL process the `context` parameter to extract known sensitive values from User_Profile (e.g., the user's `name` field) and include them as detection targets alongside regex-based patterns
7. FOR ALL valid Anonymization_Mappings, anonymizing then de-anonymizing a text SHALL produce the original text (round-trip property)

### Requirement 20: Sensitive Data Detection Patterns

**User Story:** As a developer, I want the Anonymization_Engine to detect a comprehensive set of sensitive data categories using regex patterns and known-value lookups, so that PII and secrets are reliably identified before cloud transmission.

#### Acceptance Criteria

1. THE Anonymization_Engine SHALL detect personal names by matching the `name` field from User_Profile and any names found in the memory_context provided to the Complex_Node
2. THE Anonymization_Engine SHALL detect email addresses using a regex pattern matching standard email formats (e.g., `[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}`)
3. THE Anonymization_Engine SHALL detect phone numbers using regex patterns matching common formats including international prefixes (e.g., `+1-555-123-4567`, `(555) 123-4567`, `555.123.4567`)
4. THE Anonymization_Engine SHALL detect file system paths using regex patterns matching absolute paths (e.g., paths starting with `/Users/`, `/home/`, `C:\`, or `~/)`)
5. THE Anonymization_Engine SHALL detect API keys and tokens using regex patterns matching common formats (e.g., strings starting with `sk-`, `key-`, `token-`, `Bearer `, `ghp_`, `gho_`, or alphanumeric strings of 32 or more characters preceded by key-like identifiers)
6. THE Anonymization_Engine SHALL detect IP addresses using regex patterns matching IPv4 format (e.g., `\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b`) excluding common non-sensitive addresses (`0.0.0.0`, `255.255.255.255`)
7. THE Anonymization_Engine SHALL detect localhost URLs with ports using a regex pattern matching `http://localhost:\d+` and `http://127.0.0.1:\d+` patterns
8. THE Anonymization_Engine SHALL detect Custom_Sensitive_Terms by matching each string in the `custom_sensitive_terms` list from User_Profile as a case-insensitive literal
9. THE Anonymization_Engine SHALL apply detection patterns in a priority order that processes longer matches before shorter ones to avoid partial replacements (e.g., an email address should be matched as `[EMAIL_1]` rather than having the name portion matched separately as `[NAME_1]`)

### Requirement 21: Cloud Message Anonymization in Complex Node

**User Story:** As a developer, I want the Complex_Node to anonymize all message content before sending to the Cloud_LLM, so that sensitive data in the conversation history, memory context, and system prompt is protected.

#### Acceptance Criteria

1. WHEN the Agent_State `route` is `complex-cloud`, THE Complex_Node SHALL invoke the Anonymization_Engine on all message content before sending to the Cloud_LLM
2. THE Complex_Node SHALL anonymize the `memory_context` string from Agent_State before including it in the system prompt for cloud requests
3. THE Complex_Node SHALL anonymize the `persona` string from Agent_State before including it in the system prompt for cloud requests
4. THE Complex_Node SHALL anonymize the `content` field of each `HumanMessage`, `AIMessage`, and `SystemMessage` in the conversation history before sending to the Cloud_LLM
5. THE Complex_Node SHALL pass the User_Profile `name` field and the `custom_sensitive_terms` list to the Anonymization_Engine as known sensitive values via the `context` parameter
6. THE Complex_Node SHALL store the Anonymization_Mapping in a local variable scoped to the current request (not in Agent_State or any persistent storage)
7. WHEN the Agent_State `route` is `complex-default`, `complex-vision`, or `complex-longctx`, THE Complex_Node SHALL send messages to the local M-tier model without any anonymization (data stays on the local machine)

### Requirement 22: Response De-anonymization

**User Story:** As a user, I want the Cloud_LLM response to have my original data restored in place of placeholders, so that the response reads naturally with my actual names, paths, and other values.

#### Acceptance Criteria

1. WHEN the Cloud_LLM returns a response, THE Complex_Node SHALL invoke the Anonymization_Engine `deanonymize` function on the response `content` field using the Anonymization_Mapping from the same request
2. WHEN the Cloud_LLM response contains `tool_calls`, THE Complex_Node SHALL invoke `deanonymize` on each tool call's `args` values (stringified JSON arguments) to restore original sensitive values in tool call parameters
3. IF the Cloud_LLM response contains Placeholder_Tokens that are not present in the Anonymization_Mapping (e.g., the model hallucinated a placeholder), THEN THE Complex_Node SHALL leave those tokens unchanged in the response text
4. WHEN a cloud fallback occurs (Requirement 7) and the fallback target is a local M-tier model, THE Complex_Node SHALL skip de-anonymization for the fallback response since the local model received non-anonymized input
5. THE Complex_Node SHALL perform de-anonymization before stripping `<think>` tags and before any other post-processing on the Cloud_LLM response

### Requirement 23: Anonymization Configuration

**User Story:** As a user, I want to toggle cloud data anonymization on or off and configure custom sensitive terms, so that I can control the privacy protection level for cloud API requests.

#### Acceptance Criteria

1. THE User_Profile SHALL include a `cloud_anonymization_enabled` boolean field defaulting to `true`
2. WHEN `cloud_anonymization_enabled` is `false` in User_Profile, THE Complex_Node SHALL send messages to the Cloud_LLM without invoking the Anonymization_Engine (bypassing anonymization and de-anonymization)
3. THE User_Profile SHALL include a `custom_sensitive_terms` field as a list of strings defaulting to an empty list
4. WHEN `custom_sensitive_terms` contains entries, THE Anonymization_Engine SHALL treat each entry as a case-insensitive literal match target and assign Placeholder_Tokens from the `CUSTOM` category (e.g., `[CUSTOM_1]`, `[CUSTOM_2]`)
5. WHEN the User_Profile is updated with new `custom_sensitive_terms` or a changed `cloud_anonymization_enabled` value via the REST API, THE Complex_Node SHALL use the updated values on the next cloud request without requiring a server restart


### Requirement 24: Router HITL Clarification via ask_user

**User Story:** As a user, I want the Router to ask me a clarifying question when it is genuinely unsure about how to route my request, so that ambiguous messages are handled accurately without wasting resources on the wrong model or toolbox.

#### Acceptance Criteria

1. WHEN the Router's confidence score for its routing or toolbox decision falls below the Router_Clarification_Threshold (default 0.6), THE Router SHALL invoke the `ask_user` tool via LangGraph's `interrupt()` mechanism to present a clarifying question to the user before finalizing the routing and toolbox decision
2. THE Router SHALL format the clarifying question with clear, selectable choices that map directly to routing or toolbox outcomes (e.g., `"Search the web"`, `"Work with local files"`, `"Use the cloud model for higher quality"`)
3. WHEN the Router receives the user's clarification response, THE Router SHALL use the response to finalize the `route`, `toolbox`, and `token_budget` fields in its return dictionary without invoking the Small_LLM a second time
4. WHEN the Router's confidence score is at or above the Router_Clarification_Threshold, THE Router SHALL proceed with its decision without asking the user for clarification
5. THE Router SHALL extend its output JSON to include a `needs_clarification` boolean field: `{"routing": "...", "confidence": 0.0-1.0, "toolbox": "...", "needs_clarification": true|false}`
6. THE Router SHALL limit clarification questions to a single question per turn (the Router SHALL NOT ask multiple sequential questions)
7. THE User_Profile SHALL include a `router_hitl_enabled` boolean field defaulting to `true` that controls whether the Router is allowed to ask clarifying questions
8. WHEN `router_hitl_enabled` is `false` in User_Profile, THE Router SHALL fall back to its best-guess routing and toolbox decision (equivalent to the current behavior of defaulting to `complex-default` and `all` toolbox) without invoking `ask_user`
9. THE User_Profile SHALL include a `router_clarification_threshold` float field defaulting to `0.6` that sets the confidence threshold below which the Router triggers a clarification question
10. THE LangGraph flow in `graph.py` SHALL support the Router node pausing execution via `interrupt()` and resuming with the user's clarification response before proceeding to the `simple` or `complex_llm` node
11. THE Agent_State SHALL include a `router_clarification_used` boolean field defaulting to `False` that records whether the Router asked a clarification question on the current turn, enabling downstream nodes and logging to track HITL usage
12. THE Router SHALL log the clarification question, the user's response, and the final post-clarification routing decision at `INFO` level


### Requirement 25: Redis as Short-Term Memory Checkpointer

**User Story:** As a developer, I want conversation history and graph state persisted in Redis instead of in-memory MemorySaver, so that Short_Term_Memory survives server restarts and is reliably available across all model tiers.

#### Acceptance Criteria

1. THE `docker-compose.yml` SHALL include a `redis` service using the `redis:7-alpine` image, mapping host port `6379` to container port `6379`, with a named volume `redis_data` for persistence, and `restart: unless-stopped`
2. THE `requirements.txt` SHALL include `langgraph-checkpoint-redis` as a dependency
3. THE `init_agent` function in `graph.py` SHALL create an `AsyncRedisSaver` (from `langgraph_checkpoint_redis`) connected to the Redis URL from Settings_Module (defaulting to `redis://localhost:6379`) instead of creating a `MemorySaver`
4. IF the Redis connection fails during `init_agent`, THEN THE `init_agent` function SHALL fall back to `MemorySaver` and log a warning indicating that conversation history will not persist across restarts
5. THE Settings_Module SHALL include a `REDIS_URL` configuration constant defaulting to `"redis://localhost:6379"`, overridable via the `REDIS_URL` environment variable
6. THE User_Profile SHALL include a `redis_url` field defaulting to `"redis://localhost:6379"` to allow per-user Redis endpoint configuration
7. WHEN the Redis_Checkpointer stores a checkpoint, THE Redis_Checkpointer SHALL persist the full Agent_State including `messages`, `route`, `model_used`, `selected_toolboxes`, `token_budget`, and all other Agent_State fields for the given Thread_ID
8. WHEN a new request arrives for an existing Thread_ID, THE Redis_Checkpointer SHALL restore the complete Agent_State from the previous turn so that the conversation continues with full history intact
9. THE Redis_Checkpointer SHALL isolate state by Thread_ID so that concurrent conversations do not interfere with each other
10. WHEN the `init_agent` function creates the `AsyncRedisSaver`, THE function SHALL call `await checkpointer.setup()` to initialize the Redis connection and schema before compiling the graph

### Requirement 26: Conversation Continuity Across Model Swaps

**User Story:** As a user, I want my conversation to continue seamlessly when Owlynn swaps between different models mid-chat (e.g., from Medium_Default to Medium_Vision for an image question, then back to Medium_Default), so that I experience a single coherent conversation regardless of which model handles each turn.

#### Acceptance Criteria

1. WHEN the Router selects a different M-tier variant than the currently loaded model for a new turn within the same Thread_ID, THE system SHALL preserve the full message history from all previous turns (including turns handled by other model variants) in the Agent_State `messages` field via the Redis_Checkpointer
2. WHEN a model swap occurs mid-conversation, THE memory_inject_node SHALL load context from Long_Term_Memory (Mem0/ChromaDB) and User_Profile fresh for the new turn, independent of which model produced previous responses in the thread
3. WHEN a model swap occurs mid-conversation, THE memory_write_node SHALL save facts from the current turn to Long_Term_Memory using the same `mem0_uid` scoping rules regardless of which model variant generated the response
4. WHEN the conversation escalates from a local M-tier model to the Cloud_LLM and later falls back to a local model within the same Thread_ID, THE Redis_Checkpointer SHALL maintain the complete message history across the cloud escalation and fallback so that the local model has full conversation context
5. THE Agent_State `model_used` field SHALL record the specific model variant that handled each turn (e.g., `"medium-default"`, `"medium-vision"`, `"large-cloud"`), and this per-turn provenance SHALL be preserved in the checkpointed state so that the conversation history retains attribution of which model produced each response
6. WHEN a server restart occurs and a user resumes a conversation using the same Thread_ID, THE Redis_Checkpointer SHALL restore the full conversation state including all messages from turns handled by different model variants, allowing the conversation to continue from where it left off
7. THE memory_inject_node and memory_write_node SHALL operate on message content and user identity only, with no dependency on the `model_used` or `route` fields, ensuring that Long_Term_Memory operations are fully model-agnostic


### Requirement 27: Test Suite Updates for S/M/L Architecture

**User Story:** As a developer, I want the test suite updated to cover the new three-tier routing, model swapping, dynamic tool loading, anonymization, Redis checkpointing, and conversation continuity, so that regressions are caught before deployment.

#### Acceptance Criteria

1. WHEN `test_graph.py` runs, THE test SHALL verify that `build_graph().compile()` succeeds with both a `MemorySaver` checkpointer and a mocked `AsyncRedisSaver` checkpointer
2. WHEN `test_graph.py` runs, THE test SHALL verify that the `route_decision` function correctly maps all five route values (`simple`, `complex-default`, `complex-vision`, `complex-longctx`, `complex-cloud`) to the expected graph nodes
3. THE `test_small_large_graph.py` file SHALL be renamed to `test_sml_graph.py` and updated to test graph compilation with mocked Medium_Default, Medium_Vision, Medium_LongCtx, and Cloud_LLM paths
4. WHEN `test_router_web_intent.py` runs, THE test SHALL include cases that verify Toolbox selection output (e.g., a web-search query produces `toolbox: ["web_search"]`), vision detection (image attachment routes to `complex-vision`), and cloud escalation (frontier-quality request routes to `complex-cloud`)
5. WHEN `test_sentence_routing_and_response.py` runs, THE test SHALL include parametrized cases for all five Route_Decision values: `simple`, `complex-default`, `complex-vision`, `complex-longctx`, and `complex-cloud`, verifying both the route and the `model_used` provenance value
6. THE Test_Suite SHALL include a new `test_swap_manager.py` module that tests the Swap_Manager `swap_model`, `get_current_variant`, and `get_loaded_instance_ids` methods using mocked `httpx.AsyncClient` responses for the LM_Studio_Native_API load, unload, and list endpoints
7. THE Test_Suite SHALL include a new `test_anonymization.py` module that tests the Anonymization_Engine `anonymize` and `deanonymize` functions, verifying round-trip correctness (anonymize then deanonymize produces the original text), correct Placeholder_Token format, deterministic replacement of duplicate values, priority ordering of overlapping patterns, and detection of all registered Sensitive_Pattern categories
8. THE Test_Suite SHALL include a new `test_toolbox_registry.py` module that tests the `resolve_tools` function, verifying correct tool lists for each Toolbox name, the `"all"` fallback, `web_search_enabled=False` exclusion, and that `ask_user` is always included in the result
9. THE Test_Suite SHALL include a new `test_llm_pool.py` module that tests the LLMPool `get_medium_llm`, `get_cloud_llm`, and `clear` methods using mocked Swap_Manager and `ChatOpenAI` instances, verifying cache hit behavior, variant tracking, and error handling when no API key is configured
10. THE Standalone_Tests SHALL include a new `test_redis_checkpointer.py` script in `tests/standalone/` that connects to a live Redis instance, creates an `AsyncRedisSaver`, stores and retrieves a checkpoint for a test Thread_ID, and verifies the restored Agent_State matches the stored state
11. THE Test_Suite SHALL include a new `test_conversation_continuity.py` module that tests message history preservation across simulated model swaps by invoking the compiled graph multiple times on the same Thread_ID with mocked model responses from different M-tier variants, verifying that the `messages` list grows correctly and `model_used` values are preserved per turn

### Requirement 28: Documentation Updates for S/M/L Architecture

**User Story:** As a developer, I want the documentation updated to accurately describe the new three-tier architecture, dynamic tool loading, anonymization, and Redis-backed memory, so that contributors and users can understand and extend the system.

#### Acceptance Criteria

1. WHEN `docs/ARCHITECTURE_OVERVIEW.md` is updated, THE Documentation_Set SHALL describe the S / M(swap) / L architecture with a model table listing Small_LLM, Medium_Default, Medium_Vision, Medium_LongCtx, and Cloud_LLM with their model keys, roles, approximate VRAM usage, and context window sizes
2. WHEN `docs/ARCHITECTURE_OVERVIEW.md` is updated, THE Documentation_Set SHALL include a section describing the Swap_Manager, its LM_Studio_Native_API interactions, and the constraint that only one M-tier model is loaded at a time
3. WHEN `docs/ARCHITECTURE_OVERVIEW.md` is updated, THE Documentation_Set SHALL include a section describing the Toolbox_Registry, the five Toolbox categories, the `resolve_tools` function, and the Always_Included_Tools concept
4. WHEN `docs/ARCHITECTURE_OVERVIEW.md` is updated, THE Documentation_Set SHALL include a section describing the Anonymization_Engine, its detection patterns, the anonymize/deanonymize flow for cloud requests, and the round-trip correctness property
5. WHEN `docs/ARCHITECTURE_OVERVIEW.md` is updated, THE Documentation_Set SHALL replace references to `MemorySaver` with the Redis_Checkpointer as the primary Short_Term_Memory backend and describe the fallback to `MemorySaver` when Redis is unavailable
6. WHEN `docs/ARCHITECTURE_OVERVIEW.md` is updated, THE Documentation_Set SHALL update the graph flow diagram to show the five-way routing decision (`simple`, `complex-default`, `complex-vision`, `complex-longctx`, `complex-cloud`) and the Toolbox selection step
7. WHEN `docs/guides/quickstart.md` is updated, THE Documentation_Set SHALL include setup steps for configuring the `DEEPSEEK_API_KEY` environment variable, starting the Redis container via `docker-compose`, and verifying Redis connectivity
8. WHEN `docs/guides/lm_studio.md` is updated, THE Documentation_Set SHALL describe the three M-tier model variants that must be downloaded in LM Studio (Medium_Default, Medium_Vision, Medium_LongCtx), the swap behavior, and the constraint that only one M-tier model is loaded at a time
9. WHEN `docs/guides/m4_deployment.md` is updated, THE Documentation_Set SHALL describe the memory budget for the M4 Air 24GB: LM Studio allocation (Small_LLM ~730MB + one M-tier model up to ~8.3GB + embeddings ~500MB), Podman_Machine allocation (ChromaDB + SearXNG + Redis), macOS and Python backend overhead, and the recommended Podman_Machine memory limit
10. WHEN `docs/API_REFERENCE.md` is updated, THE Documentation_Set SHALL document the `GET /api/usage` endpoint including its response schema (cumulative `prompt_tokens`, `completion_tokens`, `total_tokens` for the current session)
11. WHEN `docs/API_REFERENCE.md` is updated, THE Documentation_Set SHALL document the new User_Profile fields: `cloud_llm_base_url`, `cloud_llm_model_name`, `deepseek_api_key`, `medium_models`, `cloud_escalation_enabled`, `cloud_anonymization_enabled`, `custom_sensitive_terms`, `router_hitl_enabled`, `router_clarification_threshold`, and `redis_url`
12. WHEN `docs/TOOLS.md` is updated, THE Documentation_Set SHALL describe the Toolbox categories (`web_search`, `file_ops`, `data_viz`, `productivity`, `memory`) and explain that the Router dynamically selects which Toolbox(es) to bind per turn

### Requirement 29: Podman Machine Memory Configuration

**User Story:** As a developer deploying on a Mac M4 Air 24GB, I want the Podman_Machine explicitly configured with a memory limit, so that container services do not compete with LM Studio for unified memory and the system runs within the 24GB hardware constraint.

#### Acceptance Criteria

1. THE `setup.sh` script SHALL configure the Podman_Machine with an explicit memory limit of 4096MB (4GB) by running `podman machine init --memory 4096` when creating a new machine, or by documenting the `podman machine set --memory 4096` command for existing machines
2. THE `setup.sh` script SHALL start a Redis container alongside ChromaDB using `podman run -d --name cowork_redis -p 6379:6379 -v cowork_redis_data:/data redis:7-alpine redis-server --appendonly yes` with append-only persistence enabled
3. THE `setup.sh` script SHALL verify Redis connectivity after starting the container by running `podman exec cowork_redis redis-cli ping` and checking for a `PONG` response within 10 seconds
4. THE `start.sh` script SHALL check for the Redis container (`cowork_redis`) alongside the existing ChromaDB container check, and start it if not running
5. THE `start.sh` script SHALL verify Redis connectivity during the container startup phase by checking `redis-cli ping` or an equivalent HTTP health check before proceeding to the backend startup step
6. THE `docker-compose.yml` SHALL include a `redis` service using the `redis:7-alpine` image, mapping host port `6379` to container port `6379`, with a named volume `redis_data` for persistence, `restart: unless-stopped`, and the `--appendonly yes` command argument
7. IF the Podman_Machine does not have sufficient memory allocated (less than 2048MB), THEN THE `start.sh` script SHALL log a warning recommending the user increase the Podman_Machine memory allocation to at least 4096MB
8. THE `setup.sh` script SHALL stop and remove any existing `cowork_redis` container before starting a fresh one, following the same pattern used for the `cowork_chromadb` container
9. THE `docker-compose.yml` SHALL set a `mem_limit: 512m` on the Redis service to prevent Redis from consuming excessive memory within the Podman_Machine

### Requirement 30: Frontend Updates for S/M(swap)/L Architecture

**User Story:** As a user, I want the frontend settings, model badges, cost indicators, and swap feedback updated to reflect the three-tier S/M(swap)/L architecture, so that I can configure all model tiers, see which model produced each response, monitor cloud token usage, and receive visual feedback during model swaps.

#### Acceptance Criteria

##### Settings Panel — Profile Tab

1. WHEN the Settings_Modal Profile tab renders, THE Settings_Modal SHALL replace the "Large LLM URL" and "Large LLM Model" fields with a "Medium Models" section containing three read-only or editable fields: "Default Model" (populated from `medium_models.default` in User_Profile), "Vision Model" (populated from `medium_models.vision`), and "Long Context Model" (populated from `medium_models.longctx`)
2. WHEN the Settings_Modal Profile tab renders, THE Settings_Modal SHALL display a "Cloud (DeepSeek)" section containing three fields: "DeepSeek API URL" (populated from `cloud_llm_base_url` in User_Profile), "DeepSeek Model Name" (populated from `cloud_llm_model_name`), and "API Key" (a masked password input populated from `deepseek_api_key`, displaying `••••••••` when a key is set)
3. WHEN the user saves the Profile tab, THE Settings_Modal SHALL send the updated `medium_models`, `cloud_llm_base_url`, `cloud_llm_model_name`, and `deepseek_api_key` fields to the `POST /api/profile` endpoint alongside the existing profile fields

##### Settings Panel — Advanced Tab

4. WHEN the Settings_Modal Advanced tab renders, THE Settings_Modal SHALL display a "Routing & Cloud" card containing four controls: a "Cloud escalation enabled" toggle (bound to `cloud_escalation_enabled` in User_Profile), a "Cloud anonymization enabled" toggle (bound to `cloud_anonymization_enabled`), a "Router clarification enabled" toggle (bound to `router_hitl_enabled`), and a "Clarification threshold" range slider from 0.0 to 1.0 with step 0.05 (bound to `router_clarification_threshold`)
5. WHEN the Settings_Modal Advanced tab renders, THE Settings_Modal SHALL display a "Custom Sensitive Terms" textarea below the Routing & Cloud card, populated with the comma-separated values from the `custom_sensitive_terms` list in User_Profile
6. WHEN the user saves the Advanced tab, THE Settings_Modal SHALL parse the "Custom Sensitive Terms" textarea by splitting on commas, trimming whitespace from each entry, filtering out empty strings, and sending the resulting list as `custom_sensitive_terms` to the `POST /api/advanced-settings` endpoint

##### Settings Panel — Memory Tab

7. WHEN the Settings_Modal Memory tab renders, THE Settings_Modal SHALL display a "Redis URL" text input field (populated from `redis_url` in User_Profile, defaulting to `redis://localhost:6379`) within a "Short-Term Memory Backend" card
8. WHEN the user saves the Memory tab settings, THE Settings_Modal SHALL send the updated `redis_url` value to the `POST /api/profile` endpoint

##### Model Provenance Display

9. WHEN the WebSocket handler receives a `model_info` event containing a `model` field, THE Frontend SHALL render a Model_Badge on the current AI message displaying the model value (e.g., `"small-local"`, `"medium-default"`, `"medium-vision"`, `"medium-longctx"`, `"large-cloud"`, or fallback variants)
10. WHEN the Model_Badge displays a `model` value starting with `"small"`, THE Model_Badge SHALL use a gray background (`#374151` background, `#9ca3af` text) with no icon
11. WHEN the Model_Badge displays a `model` value starting with `"medium"`, THE Model_Badge SHALL use a blue background (`#1e3a5f` background, `#93c5fd` text, `#2563eb` border)
12. WHEN the Model_Badge displays a `model` value starting with `"large"`, THE Model_Badge SHALL use a purple background (`#2b2646` background, `#d3c8ff` text, `#483d7a` border) with a cloud icon (SVG: 16x16 cloud outline)
13. WHEN the Model_Badge displays a `model` value containing `"fallback"`, THE Model_Badge SHALL use an orange background (`#451a03` background, `#fdba74` text, `#92400e` border) with a warning icon (SVG: 16x16 triangle-alert outline)

##### Cost / Usage Display

14. WHEN the WebSocket handler receives a `message` event containing a `token_usage` object with `prompt_tokens` and `completion_tokens` fields, THE Frontend SHALL render a Cloud_Token_Indicator adjacent to the Model_Badge showing the token counts in the format "↑{prompt_tokens} ↓{completion_tokens}"
15. WHEN the `token_usage` object is absent or both token counts are zero, THE Frontend SHALL hide the Cloud_Token_Indicator for that message
16. THE Frontend SHALL provide a clickable link or button in the Settings_Modal or status bar that opens the `/api/usage` endpoint response in a formatted view showing cumulative session token usage (`prompt_tokens`, `completion_tokens`, `total_tokens`)

##### Router Clarification UI

17. WHEN the WebSocket handler receives an `ask_user` event where the question contains routing choices, THE Frontend SHALL render each choice as a clickable button within the existing `handleAskUserInterrupt` card, styled as `.ask-choice-btn` elements
18. WHEN the user clicks a routing choice button, THE Frontend SHALL send the selected choice text as the response to the `ask_user` interrupt via the WebSocket, following the same protocol used for other HITL interactions

##### Model Swap Indicator

19. WHEN the WebSocket handler receives a `model_info` event containing a `swapping` field set to `true`, THE Frontend SHALL display a Model_Swap_Indicator status message (e.g., "Switching to vision model...") below the thinking indicator or in the status bar area
20. WHEN the WebSocket handler receives a subsequent `model_info` event with `swapping` set to `false` or absent, THE Frontend SHALL remove the Model_Swap_Indicator

