# Implementation Plan: DeepSeek Hybrid Integration

## Overview

Transform Owlynn from a dual-LLM (small + large) architecture to a three-tier S / M(swap) / L hybrid system. Implementation proceeds foundation-first: settings and state updates, then core infrastructure (LLMPool, SwapManager, Redis), then routing and tool system, then anonymization and complex node, then server and frontend, then infrastructure scripts, and finally tests and documentation.

## Tasks

- [x] 1. Foundation: Settings, User Profile, and Agent State updates
  - [x] 1.1 Update `src/config/settings.py` with new constants
    - Add `REDIS_URL` from env var defaulting to `redis://localhost:6379`
    - Add `DEEPSEEK_API_KEY` from env var
    - Add context window constants: `MEDIUM_DEFAULT_CONTEXT = 100000`, `MEDIUM_LONGCTX_CONTEXT` (env, default 131072), `CLOUD_CONTEXT = 131072`
    - Add `M4_MAC_OPTIMIZATION["large_model"]["cloud_timeout"] = 180`
    - Add `M4_MAC_OPTIMIZATION["medium_models"]` with `swap_timeout: 120`, `poll_interval: 2`
    - _Requirements: 5.1, 5.2, 5.3, 7.7, 25.5_

  - [x] 1.2 Update `src/memory/user_profile.py` with new profile fields and defaults
    - Add `cloud_llm_base_url` (default `https://api.deepseek.com/v1`)
    - Add `cloud_llm_model_name` (default `deepseek-chat`)
    - Add `deepseek_api_key` (default `""`)
    - Add `medium_models` dict with `default`, `vision`, `longctx` keys
    - Add `cloud_escalation_enabled` (default `true`)
    - Add `cloud_anonymization_enabled` (default `true`)
    - Add `custom_sensitive_terms` (default `[]`)
    - Add `router_hitl_enabled` (default `true`)
    - Add `router_clarification_threshold` (default `0.6`)
    - Add `redis_url` (default `redis://localhost:6379`)
    - Update `_DEFAULTS` and `VALID_FIELDS` dicts
    - _Requirements: 10.1, 10.2, 10.3, 10.4, 10.5, 10.6, 23.1, 23.3, 24.7, 24.9, 25.6_

  - [x] 1.3 Update `data/user_profile.json` with new default fields
    - Add all new fields from 1.2 with their default values
    - _Requirements: 10.1, 10.2, 10.3, 10.4_

  - [x] 1.4 Update `src/agent/state.py` with expanded Agent State fields
    - Change `route` type annotation to accept 5-way values: `"simple"`, `"complex-default"`, `"complex-vision"`, `"complex-longctx"`, `"complex-cloud"`
    - Change `model_used` to accept expanded provenance values: `"small-local"`, `"medium-default"`, `"medium-vision"`, `"medium-longctx"`, `"large-cloud"`, and fallback variants
    - Add `current_medium_model: str | None`
    - Add `selected_toolboxes: list[str] | None`
    - Add `api_tokens_used: dict | None`
    - Add `router_clarification_used: bool | None`
    - _Requirements: 14.1, 14.2, 14.3, 14.4, 18.1, 18.2, 18.3, 24.11_

  - [x] 1.5 Update `requirements.txt` with new dependencies
    - Add `langgraph-checkpoint-redis`
    - Verify `httpx` is already present (it is)
    - Add `hypothesis` for property-based testing in dev requirements
    - _Requirements: 25.2_

- [x] 2. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 3. Core infrastructure: LLMPool refactor and SwapManager
  - [x] 3.1 Create `src/agent/swap_manager.py` (new file)
    - Implement `ModelSwapError` exception class
    - Implement `SwapManager` class with `httpx.AsyncClient`
    - Implement `swap_model(target_variant)` — unload current, load target via LM Studio native API
    - Implement `get_current_variant()` method
    - Implement `get_loaded_instance_ids(model_key)` method
    - Poll `GET /api/v1/models` until target loaded, with configurable timeout (120s) and poll interval (2s)
    - Read model keys from `User_Profile["medium_models"]`
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8, 3.9_

  - [x] 3.2 Write property test for SwapManager variant-to-key mapping
    - **Property 9: Swap Manager Variant-to-Key Mapping**
    - **Validates: Requirements 3.1**

  - [x] 3.3 Refactor `src/agent/llm.py` — 3-slot LLMPool (small + medium + cloud)
    - Replace `_large_llm` with `_medium_llm` and `_cloud_llm`
    - Add `_current_medium_variant: Optional[str] = None`
    - Implement `get_medium_llm(variant: str = "default")` — cache hit if variant matches, else trigger SwapManager
    - Implement `get_cloud_llm()` — DeepSeek API client with `streaming=True`, `max_tokens=8192`, `temperature=0.4`, no `extra_body`
    - API key resolution: `DEEPSEEK_API_KEY` env var → `deepseek_api_key` in User_Profile → raise error
    - Keep `get_large_llm()` as alias for `get_medium_llm("default")` for backward compatibility
    - Update `clear()` to reset all three slots and `_current_medium_variant`
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7, 2.8, 2.9_

  - [x] 3.4 Write property tests for LLMPool
    - **Property 3: LLMPool Variant Tracking** — `_current_medium_variant` always matches last successful call
    - **Validates: Requirements 2.2, 2.4, 2.5, 2.9**
    - **Property 10: API Key Resolution Order** — env var > profile > disabled
    - **Validates: Requirements 1.1, 1.2**

  - [x] 3.5 Update `src/agent/lm_studio_compat.py` — add `is_local_server()`
    - Implement `is_local_server(base_url: str) -> bool` — True if URL contains `127.0.0.1` or `localhost`
    - _Requirements: 9.1, 9.3_

  - [x] 3.6 Write property test for is_local_server
    - **Property 6: is_local_server Classification**
    - **Validates: Requirements 9.1, 9.3**

- [x] 4. Redis checkpointer integration
  - [x] 4.1 Update `src/agent/graph.py` — Redis checkpointer and 5-way routing
    - Import `AsyncRedisSaver` from `langgraph_checkpoint_redis`
    - Update `init_agent` to create `AsyncRedisSaver` with `REDIS_URL`, call `await checkpointer.setup()`, fall back to `MemorySaver` on failure
    - Update `route_decision` to accept 5 valid routes: `simple`, `complex-default`, `complex-vision`, `complex-longctx`, `complex-cloud` — all complex-* map to `complex_llm` node
    - Default unrecognized routes to `complex-default` (mapped to `complex_llm`)
    - _Requirements: 13.1, 13.2, 13.3, 13.4, 25.3, 25.4, 25.7, 25.8, 25.9, 25.10_

- [x] 5. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 6. Routing: 5-way router with toolbox selection
  - [x] 6.1 Update `src/agent/tool_sets.py` — add ToolboxRegistry and resolve_tools
    - Add `TOOLBOX_REGISTRY` dict mapping toolbox names to tool lists
    - Add `ALWAYS_INCLUDED_TOOLS = [ask_user]`
    - Implement `resolve_tools(toolbox_names, web_search_enabled)` — union of requested toolboxes + always-included, `"all"` returns full set, `web_search_enabled=False` excludes web tools
    - Keep existing `COMPLEX_TOOLS_WITH_WEB` and `COMPLEX_TOOLS_NO_WEB` for backward compatibility
    - _Requirements: 15.1, 15.2, 15.3, 15.4, 15.5, 15.6, 15.7, 15.8, 15.9, 15.10_

  - [x] 6.2 Write property test for resolve_tools
    - **Property 5: Resolve Tools Produces Correct Union**
    - **Validates: Requirements 15.7, 15.8, 15.9, 15.10**

  - [x] 6.3 Update `src/agent/nodes/router.py` — 5-way routing with toolbox selection and HITL
    - Update `ROUTER_PROMPT` to include toolbox classification and `needs_clarification` field
    - Implement two-stage decision: simple vs complex, then variant selection for complex
    - Stage 2 logic: image attachments → `complex-vision`, token count > 80% Medium_Default → `complex-longctx`, exceeds Medium_LongCtx → `complex-cloud`, default → `complex-default`
    - Prefer currently-loaded variant when borderline (avoid swap latency)
    - Add toolbox selection output: `web_search`, `file_ops`, `data_viz`, `productivity`, `memory`, `all`
    - Implement HITL clarification via `interrupt()` when confidence < threshold and `router_hitl_enabled`
    - Update `estimate_token_budget` for per-tier context windows
    - Return `route`, `token_budget`, `selected_toolboxes`, `router_clarification_used` in state
    - If no valid DeepSeek API key, route cloud-eligible tasks to local models
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7, 4.8, 4.9, 5.4, 5.5, 5.6, 5.7, 5.8, 16.1, 16.2, 16.3, 16.4, 16.5, 16.6, 16.7, 16.8, 16.9, 16.10, 16.11, 18.4, 24.1, 24.2, 24.3, 24.4, 24.5, 24.6, 24.8, 24.9, 24.10, 24.12_

  - [x] 6.4 Write property tests for router
    - **Property 2: Route Decision Domain** — route ∈ valid set, image → vision, token overflow → longctx/cloud
    - **Validates: Requirements 4.1, 4.3, 4.4, 4.5, 4.6**
    - **Property 4: Token Budget Uses Correct Context Window** — budget computed with correct constant per route
    - **Validates: Requirements 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 5.7, 5.8**
    - **Property 15: Router HITL Threshold Behavior** — clarification iff confidence < threshold AND enabled
    - **Validates: Requirements 24.1, 24.4, 24.7, 24.8**

- [x] 7. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 8. Anonymization engine
  - [x] 8.1 Create `src/agent/anonymization.py` (new file)
    - Implement `anonymize(text, context) -> (anonymized_text, mapping)` with detection categories in priority order:
      1. API keys/tokens (sk-, key-, Bearer, ghp_, 32+ char alphanumeric)
      2. Email addresses
      3. URLs with localhost ports
      4. File system paths (/Users/, /home/, C:\, ~/)
      5. IP addresses (excluding 0.0.0.0, 255.255.255.255)
      6. Phone numbers (international formats)
      7. Known names (from context `name` field)
      8. Custom sensitive terms (from context `custom_sensitive_terms`)
    - Implement `deanonymize(text, mapping) -> str` — restore placeholders to original values
    - Placeholder format: `[CATEGORY_N]` (e.g., `[NAME_1]`, `[EMAIL_1]`)
    - Same sensitive value → same placeholder (deterministic within request)
    - Longest match first to prevent partial replacements
    - _Requirements: 19.1, 19.2, 19.3, 19.4, 19.5, 19.6, 19.7, 20.1, 20.2, 20.3, 20.4, 20.5, 20.6, 20.7, 20.8, 20.9_

  - [x] 8.2 Write property tests for anonymization
    - **Property 1: Anonymization Round-Trip** — `deanonymize(anonymize(text, ctx)) == text`
    - **Validates: Requirements 19.3, 19.4, 19.7**
    - **Property 14: Sensitive Pattern Detection Coverage** — all categories detected, longest-first
    - **Validates: Requirements 20.2, 20.3, 20.4, 20.5, 20.6, 20.9**

- [x] 9. Complex node: model selection, anonymization, dynamic tools, fallback chains
  - [x] 9.1 Update `src/agent/nodes/complex.py` — model selection by route
    - Read `route` from Agent_State to select model via LLMPool:
      - `complex-default` → `get_medium_llm("default")`
      - `complex-vision` → `get_medium_llm("vision")`
      - `complex-longctx` → `get_medium_llm("longctx")`
      - `complex-cloud` → `get_cloud_llm()`
    - Use `is_local_server()` to decide message format: folded for local, standard OpenAI for cloud
    - Set `model_used` in returned state: `"medium-default"`, `"medium-vision"`, `"medium-longctx"`, `"large-cloud"`
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 6.8, 9.1, 9.2, 11.1, 11.2, 11.3, 11.4_

  - [x] 9.2 Integrate anonymization into complex node for cloud route
    - When route is `complex-cloud` AND `cloud_anonymization_enabled` is True:
      - Anonymize memory_context, persona, and all message content before sending
      - Pass User_Profile `name` and `custom_sensitive_terms` as context
      - Store mapping in local variable (not in state)
      - Deanonymize response content and tool call args after receiving
      - Perform deanonymization before stripping `<think>` tags
    - Skip anonymization for all local routes
    - Skip deanonymization when cloud falls back to local model
    - _Requirements: 21.1, 21.2, 21.3, 21.4, 21.5, 21.6, 21.7, 22.1, 22.2, 22.3, 22.4, 22.5, 23.2, 23.5_

  - [x] 9.3 Integrate dynamic tool binding from ToolboxRegistry
    - Read `selected_toolboxes` from Agent_State
    - Call `resolve_tools(selected_toolboxes, web_search_enabled)` to get tool list
    - Fall back to full tool set when `selected_toolboxes` is None or contains `"all"`
    - Use resolved tools for both `bind_tools()` and `ToolNode` in `complex_tool_action_node`
    - Include previously-used tools when conversation has tool history from different toolbox
    - _Requirements: 17.1, 17.2, 17.3, 17.4, 17.5, 17.7_

  - [x] 9.4 Implement tiered fallback chains
    - Cloud failure → retry with Medium_Default; HTTP 401/403 → append API key note; HTTP 429 → retry after 2s delay then Medium_Default
    - Vision failure → Medium_Default
    - LongCtx failure → Cloud first, then Medium_Default with truncated context
    - ModelSwapError → use currently-loaded M-tier variant
    - Set `model_used` with `-fallback` suffix on all fallbacks
    - Apply correct message format for fallback model
    - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5, 7.6, 11.6_

  - [x] 9.5 Extract and track cloud token usage
    - Extract `prompt_tokens` and `completion_tokens` from DeepSeek API response metadata
    - Set `api_tokens_used` in Agent_State
    - _Requirements: 12.1, 12.2_

  - [x] 9.6 Write property tests for complex node behavior
    - **Property 7: Model Provenance Matches Route** — model_used corresponds to route
    - **Validates: Requirements 11.1, 11.2, 11.3, 11.4, 11.5, 11.6**
    - **Property 8: Cloud-Only Anonymization** — anonymization iff cloud route AND enabled
    - **Validates: Requirements 21.1, 21.7, 23.2**

- [x] 10. Simple node update
  - [x] 10.1 Update `src/agent/nodes/simple.py` — set `model_used` to `"small-local"`
    - Change `model_used` from `"small"` to `"small-local"` and fallback from `"large"` to `"medium-default-fallback"`
    - _Requirements: 11.5_

- [x] 11. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 12. Server: API endpoints and WebSocket updates
  - [x] 12.1 Update `src/api/server.py` — new endpoints and WebSocket enhancements
    - Add `GET /api/usage` endpoint returning cumulative session token usage (`prompt_tokens`, `completion_tokens`, `total_tokens`)
    - Include `model_used` and `token_usage` fields in WebSocket response messages
    - Send `model_info` WebSocket events with `swapping` flag during M-tier swaps
    - Trigger `LLMPool.clear()` when cloud/medium profile fields change on save
    - Update `POST /api/profile` to accept new fields (medium_models, cloud fields, etc.)
    - Update `POST /api/advanced-settings` to accept cloud/anonymization/HITL toggles and custom_sensitive_terms
    - _Requirements: 8.3, 11.7, 12.3, 12.4, 30.3_

- [x] 13. Frontend updates
  - [x] 13.1 Update `frontend/index.html` — Settings panel changes
    - Profile tab: Replace "Large LLM" fields with "Medium Models" section (3 fields: default, vision, longctx) + "Cloud (DeepSeek)" section (URL, model, masked API key)
    - Advanced tab: Add "Routing & Cloud" card with cloud escalation toggle, anonymization toggle, HITL toggle, threshold slider + "Custom Sensitive Terms" textarea
    - Memory tab: Add "Redis URL" text input in "Short-Term Memory Backend" card
    - _Requirements: 30.1, 30.2, 30.4, 30.5, 30.7_

  - [x] 13.2 Update `frontend/script.js` — model badges, token indicators, swap indicator
    - Implement tier-colored model badges: gray (small), blue (medium), purple (cloud), orange (fallback)
    - Implement Cloud_Token_Indicator: `↑{prompt} ↓{completion}` next to badge
    - Implement swap indicator: transient "Switching to vision model..." message on `model_info` events
    - Handle Router clarification choices as clickable buttons via `handleAskUserInterrupt`
    - Update `loadSettingsData` to populate new profile/advanced fields
    - Update save handlers to send new fields to API
    - _Requirements: 30.6, 30.8, 30.9, 30.10, 30.11, 30.12, 30.13, 30.14, 30.15, 30.16, 30.17, 30.18, 30.19, 30.20_

  - [x] 13.3 Update `frontend/style.css` — tier-colored badge styles
    - Add `.model-badge-small` (gray), `.model-badge-medium` (blue), `.model-badge-cloud` (purple), `.model-badge-fallback` (orange)
    - Add `.cloud-token-indicator` styles
    - Add `.swap-indicator` styles
    - _Requirements: 30.10, 30.11, 30.12, 30.13_

- [x] 14. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 15. Infrastructure: Docker, setup.sh, start.sh
  - [x] 15.1 Update `docker-compose.yml` — add Redis service
    - Add `redis` service: `redis:7-alpine`, port 6379, volume `redis_data`, `--appendonly yes`, `mem_limit: 512m`, `restart: unless-stopped`
    - Add `redis_data` volume
    - _Requirements: 25.1, 29.6, 29.9_

  - [x] 15.2 Update `setup.sh` — Podman memory config and Redis container
    - Add `podman machine init --memory 4096` or document `podman machine set --memory 4096`
    - Stop/remove existing `cowork_redis` container
    - Start Redis container: `podman run -d --name cowork_redis -p 6379:6379 -v cowork_redis_data:/data redis:7-alpine redis-server --appendonly yes`
    - Verify Redis connectivity: `podman exec cowork_redis redis-cli ping` with 10s timeout
    - _Requirements: 29.1, 29.2, 29.3, 29.8_

  - [x] 15.3 Update `start.sh` — Redis container check and connectivity
    - Check for `cowork_redis` container alongside `cowork_chromadb`
    - Start Redis if not running
    - Verify Redis connectivity before backend startup
    - Warn if Podman_Machine memory < 2048MB
    - _Requirements: 29.4, 29.5, 29.7_

- [x] 16. Streaming support verification
  - [x] 16.1 Verify streaming works for cloud and local models
    - Ensure Cloud_LLM has `streaming=True`
    - Ensure WebSocket handler forwards token chunks from both local and cloud sources
    - Handle cloud connection interruptions by returning partial content
    - _Requirements: 8.1, 8.2, 8.3, 8.4_

- [x] 17. Test suite: new test modules and updated existing tests
  - [x] 17.1 Create `tests/test_swap_manager.py`
    - Test `swap_model` with mocked httpx responses for load/unload/list
    - Test `get_current_variant` tracking
    - Test `get_loaded_instance_ids`
    - Test timeout and `ModelSwapError` handling
    - Test unload failure → proceed with load
    - _Requirements: 27.6_

  - [x] 17.2 Create `tests/test_anonymization.py`
    - Unit tests: round-trip, placeholder format, deterministic duplicates, priority ordering, all pattern categories
    - Edge cases: empty text, no sensitive data, overlapping patterns, unknown placeholders in deanonymize
    - _Requirements: 27.7_

  - [x] 17.3 Create `tests/test_toolbox_registry.py`
    - Test each toolbox name returns correct tools
    - Test `"all"` returns full set
    - Test `web_search_enabled=False` excludes web tools
    - Test `ask_user` always included
    - _Requirements: 27.8_

  - [x] 17.4 Create `tests/test_llm_pool.py`
    - Test `get_medium_llm` cache hit/miss behavior
    - Test variant tracking after sequential calls
    - Test `get_cloud_llm` with/without API key
    - Test `clear()` resets all state
    - _Requirements: 27.9_

  - [x] 17.5 Create `tests/test_conversation_continuity.py`
    - Test message history preservation across simulated model swaps on same Thread_ID
    - Test `model_used` provenance preserved per turn
    - _Requirements: 27.11_

  - [x] 17.6 Update `tests/test_graph.py` — 5-way routing and Redis mock
    - Verify `build_graph().compile()` with MemorySaver and mocked AsyncRedisSaver
    - Verify `route_decision` maps all 5 routes correctly
    - _Requirements: 27.1, 27.2_

  - [x] 17.7 Update `tests/test_router_web_intent.py` — toolbox selection and vision/cloud tests
    - Add cases for toolbox selection output
    - Add vision detection (image attachment → complex-vision)
    - Add cloud escalation test
    - _Requirements: 27.4_

  - [x] 17.8 Rename `tests/test_small_large_graph.py` to `tests/test_sml_graph.py` and update
    - Update for S/M/L paths with mocked Medium_Default, Medium_Vision, Medium_LongCtx, Cloud_LLM
    - _Requirements: 27.3_

  - [x] 17.9 Create `tests/standalone/test_redis_checkpointer.py`
    - Connect to live Redis, create AsyncRedisSaver, store/retrieve checkpoint
    - Verify restored Agent_State matches stored state
    - Verify thread isolation
    - _Requirements: 27.10_

  - [x] 17.10 Write property test for conversation continuity
    - **Property 12: Conversation Continuity Across Swaps** — all messages preserved, model_used provenance maintained
    - **Validates: Requirements 26.1, 26.5**

  - [x] 17.11 Write property test for Redis checkpoint round-trip
    - **Property 11: Redis Checkpoint Round-Trip** — store then retrieve = identical state, thread isolation
    - **Validates: Requirements 25.7, 25.8, 25.9**

  - [x] 17.12 Write property test for model badge color mapping
    - **Property 13: Model Badge Color Mapping** — prefix → color mapping
    - **Validates: Requirements 30.10, 30.11, 30.12, 30.13**

- [x] 18. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 19. Documentation updates
  - [x] 19.1 Update `docs/ARCHITECTURE_OVERVIEW.md`
    - Describe S/M(swap)/L architecture with model table
    - Add SwapManager section
    - Add ToolboxRegistry section
    - Add AnonymizationEngine section
    - Replace MemorySaver references with Redis_Checkpointer
    - Update graph flow diagram for 5-way routing
    - _Requirements: 28.1, 28.2, 28.3, 28.4, 28.5, 28.6_

  - [x] 19.2 Update `docs/guides/quickstart.md`
    - Add DeepSeek API key setup steps
    - Add Redis container setup via docker-compose
    - Add Redis connectivity verification
    - _Requirements: 28.7_

  - [x] 19.3 Update `docs/guides/lm_studio.md`
    - Describe three M-tier model variants to download
    - Describe swap behavior and one-at-a-time constraint
    - _Requirements: 28.8_

  - [x] 19.4 Update `docs/guides/m4_deployment.md`
    - Describe memory budget: LM Studio allocation, Podman_Machine allocation, macOS overhead
    - Recommend Podman_Machine memory limit of 4096MB
    - _Requirements: 28.9_

  - [x] 19.5 Update `docs/API_REFERENCE.md`
    - Document `GET /api/usage` endpoint and response schema
    - Document new User_Profile fields
    - _Requirements: 28.10, 28.11_

  - [x] 19.6 Update `docs/TOOLS.md`
    - Describe Toolbox categories and dynamic selection
    - _Requirements: 28.12_

- [x] 20. Final checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate universal correctness properties from the design document
- Unit tests validate specific examples and edge cases
- The `get_large_llm()` alias is kept during migration for backward compatibility
- Frontend tasks (13.x) can be parallelized with backend tasks if needed
- Infrastructure tasks (15.x) should be done before running integration tests
