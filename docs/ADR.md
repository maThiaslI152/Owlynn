# Architecture Decision Log (ADR)

This log records the significant architectural decisions for the Owlynn project,
following the [ADR pattern](https://adr.github.io/). Each entry captures the context,
decision, and consequences of a key design choice.

## ADR-0001: Tauri as Desktop Shell

**Date:** 2026-04-23

**Status:** Implemented with Tauri v1; v2 migration tracked for future.

**Context:** Owlynn needed a native desktop shell to support local-first operation with
screen capture, push-to-talk, and security controls. Options included Electron, Tauri v1/v2,
and bare Python GUI frameworks.

**Decision:** Tauri v1 with React + TypeScript frontend, using macOS native vibrancy.

**Consequences:**
- Native window management and OS-level permissions (screen capture, mic) via Tauri commands.
- Rust backend for security-critical paths, separate from Python agent.
- Smaller binary size compared to Electron (~5MB vs ~100MB).
- Uses Tauri v1 (stable, mature ecosystem) rather than v2 (newer API surface). v2 migration
  is deferred — it would require rewriting `tauri.conf.json` format, command registration,
  and permission model, with no immediate benefit for the current feature set.
- Requires Tauri permission audit before production release.

---

## ADR-0002: LangGraph for Agent Orchestration

**Date:** 2026-04-23

**Context:** The agent needs a stateful, cyclic execution graph for routing, tool execution,
memory management, and security gating. Options included LangGraph, custom state machines,
and other agent frameworks.

**Decision:** LangGraph with Python `StateGraph` and `AgentState` TypedDict.

**Consequences:**
- State transitions are explicit and testable via conditional edges.
- Supports cyclic flows (tool call → security → action → LLM loop).
- Redis-backed checkpointing for persistence across restarts.
- Checkpoint system enables thread-level conversation history.

---

## ADR-0003: Local-First Hybrid Model Architecture

**Date:** 2026-04-23

**Context:** The assistant must work fully offline while optionally escalating to cloud models
for complex tasks. Models need tiered routing based on task complexity.

**Decision:** Three-tier model system: Small LLM (always local), Medium LLM (local, default),
Large LLM (optional cloud via DeepSeek).

**Consequences:**
- Small LLM (`gemma-4-e2b-heretic-uncensored-mlx`, 4K context) for routing and simple tasks.
- Medium LLM (`lfm2-8b-a1b-absolute-heresy-mpoa-mlx`, 100K context) for complex tasks.
- Cloud fallback (DeepSeek) for coding and long-context tasks when available.
- `LLMPool` manages lifecycle — clears when profile changes trigger model swap.
- Model keys stored in runtime profile, changeable without server restart.

---

## ADR-0004: WebSocket as Primary Frontend-Backend Transport

**Date:** 2026-04-23

**Context:** The frontend needs real-time streaming of LLM responses, tool execution events,
and voice state changes. REST polling would be too slow for chat UX.

**Decision:** Single persistent WebSocket connection per thread (`/ws/chat/{thread_id}`)
with JSON event framing.

**Consequences:**
- Event types defined in `docs/CHAT_PROTOCOL.md` with strict shape contracts.
- `WsClient` TypeScript wrapper provides lifecycle callbacks and send-gating.
- Rust Tauri events (voice, screen assist) are forwarded through a parallel channel.
- Connection established per-thread; disconnects don't cancel running graph execution.

---

## ADR-0005: Mem0 + Qdrant for Long-Term Memory

**Date:** 2026-04-23

**Context:** The assistant needs persistent cross-session memory with semantic search.
Options included Mem0 with FAISS, ChromaDB, or Qdrant.

**Decision:** Mem0 with local Qdrant on port 6333, LM Studio embeddings
(`nomic-embed-text-v1.5`).

**Consequences:**
- Memory is namespace-scoped by project (`project:<id>`) and user identity.
- Topic extraction and enriched memory save on every conversation turn.
- Memory context TTL-cached (5 min) in `MemoryContextCache` for M4 optimization.
- Requires Qdrant container running for memory functionality.

---

## ADR-0006: Security Proxy with HITL Approval

**Date:** 2026-04-23

**Context:** The agent needs guardrails around destructive actions (file deletion,
code execution, data modification). The system must support both automatic approval
and human-in-the-loop authorization.

**Decision:** Mandatory `security_proxy` node in LangGraph graph with risk classification
and configurable execution policy (`hitl` / `auto_approve`).

**Consequences:**
- Every tool call goes through security proxy before execution.
- Risk metadata (label, confidence, rationale, remediation) is classified server-side.
- Frontend shows `ActionProposalQueue` for pending approvals.
- Audit trail of all tool executions with hash-verified export.

---

## ADR-0007: Redis for Hot State, Qdrant for Vector Memory

**Date:** 2026-04-23 (updated 2026-04-23 to reflect actual Qdrant usage)

**Context:** The agent needs fast session state (active conversations) and durable
vector storage (long-term memory, semantic search).

**Decision:** Redis for session state and LangGraph checkpointing; Qdrant for vector
memory (accessed via Mem0); SearxNG for local web retrieval.

**Consequences:**
- Redis provides sub-millisecond session state access.
- Qdrant (on port 8100) with `nomic-embed-text-v1.5` embeddings for memory vector storage.
- Mem0 wraps Qdrant for higher-level memory operations (topic extraction, enriched memory).
- SearxNG enables privacy-preserving local web search.
- Qdrant, Redis, and SearxNG run in containers (`docker-compose.yml`).

---

## ADR-0008: Unfiltered Content Policy with Strict Tool Controls

**Date:** 2026-04-23

**Context:** The assistant is designed for a personal-use local assistant with no
content-behavior filters, but must maintain security around destructive actions.

**Decision:** No content-behavior filters applied to model outputs. Strict tool-level
permissions with destructive-action confirmations and tamper-evident audit trail.

**Consequences:**
- Models produce unfiltered output (user is responsible for content).
- Tool execution requires explicit approval for risky operations.
- All tool actions are logged with HMAC-signed audit hashes.
- Audit bundles can be exported and verified for tamper evidence.

---

## ADR-0009: Zustand for Frontend State Management

**Date:** 2026-04-23

**Context:** The React frontend needs a simple, typed state store that integrates with
WebSocket events and Tauri runtime events without boilerplate.

**Decision:** Zustand with single `useAppStore` store for all frontend state.

**Consequences:**
- No Redux middleware or context provider nesting required.
- State mutations are colocated with the store definition.
- `verbatimModuleSyntax` requirement in TypeScript config.
- TypeScript types for `ChatMessage`, `ToolExecutionSnapshot`, `ActionProposal` etc.

---

## ADR-0010: WebSocket Event Telemetry for Routing and Fallback Visibility

**Date:** 2026-04-23

**Context:** Without runtime visibility into routing decisions and model fallback chains,
debugging unexpected behavior is difficult. The backend needed to expose internal
orchestration state to the frontend.

**Decision:** Emit `router_info` event on every routing decision and `fallback_chain`
in `model_info` events.

**Consequences:**
- `router_info` contains route, confidence, reasoning, classification_source, features.
- `fallback_chain` tracks ordered model attempts with status, reason, duration_ms.
- Both events have WS contract tests (`test_ws_router_info_event_emitted`, etc.).
- Frontend `OrchestrationPanel` displays routing and model information.
- Non-serializable metadata fields silently dropped with warning log.

---

## ADR-0011: Auto-Summarize with Multi-Level Compression

**Date:** 2026-04-23

**Context:** Long-running conversations can exceed the model's context window.
A naive truncation would lose important context. The system needed automatic
context compression.

**Decision:** Auto-summarize LangGraph node triggered at >85% context window usage,
with structured categorized output and prior-summary awareness.

**Consequences:**
- Small LLM produces structured summary (decisions, facts, preferences, tasks, code).
- Prior auto-summaries are fed back into subsequent compression rounds.
- Protected messages (tool results, pinned, system) are never compressed.
- `context_summarized` WebSocket event emitted on compression.
- Graceful degradation — LLM failure results in no-op (keep full context).
