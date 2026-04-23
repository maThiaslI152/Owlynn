# AI Rebuild Master Plan (Canonical)

## Purpose

This document is the canonical multi-agent implementation handoff for the Owlynn near-rebuild.

It is designed so Cursor, Antigravity, PearAI, and other coding agents can resume work consistently without re-deriving architecture decisions.

## Source of truth order

1. `docs/STATUS.md` (current operational truth)
2. `docs/AI_AGENT_INDEX.md` (navigation index)
3. `docs/AI_MULTI_AGENT_RESUME_PLAYBOOK.md` (resume protocol)
4. `docs/AI_REBUILD_MASTER_PLAN.md` (this document)
5. Active planning artifact under `.cursor/plans/` (reference only; do not mutate unless explicitly requested)

If there is conflict:
- current runtime state -> `docs/STATUS.md`
- rebuild direction and sequencing -> this file

## Locked direction

- Desktop shell: `Tauri v2`
- Frontend: `React + TypeScript` rebuild from zero
- Data stack:
  - `Redis` for runtime/session hot state
  - `ChromaDB` for long-term vector memory (via Mem0)
  - `SearxNG` for web retrieval
- Model roles:
  - `gemma-4-e2b-heretic-uncensored-mlx` = fast path
  - `lfm2-8b-a1b-absolute-heresy-mpoa-mlx` = big-brain escalation
- Security posture:
  - no behavior/content censorship layer
  - strict tool permissions + destructive-action confirmations
  - tamper-evident auditing
- Memory posture:
  - cross-session continuity by default
  - namespace isolation (`personal`, `project`, `ctf`)

## Core backbone to keep (OpenClaw-aligned)

Preserve these responsibilities while rebuilding UI/runtime edges:

- Gateway/control-plane orchestration patterns
- Tool permission and approval pathways
- Session and project continuity semantics
- Memory/event plumbing contracts (typed, auditable, resumable)

## Productionized capability picks (Cookbook-derived)

Implement these first as durable modules:

1. Retrieval + context grounding pipeline (RAG-first assistance)
2. Routing + escalation workflow (fast model vs big-brain model)
3. Evaluator loop for quality gates on important actions

These three give maximum day-to-day value for local assistant usage while remaining testable.

## Minimal rules/hooks profile (ECC-inspired, adapted)

Use a minimal profile only:

- Pre-action checks:
  - tool permission check
  - destructive-action confirmation check
  - provenance check (trusted user intent vs external content)
- Post-action logging:
  - structured event audit record
  - status/result + latency + policy version
- Fail-safe behaviors:
  - deny by default on ambiguous provenance
  - auto-enter safe mode on repeated integrity failures

Avoid broad behavioral filters; keep focus on system security and execution controls.

## MVP scope lock

- Channels:
  - desktop chat/live-talk first (no broad channel expansion before stability)
- Tools:
  - local filesystem/workspace tools, controlled shell/tool execution, retrieval stack access
- Memory policy:
  - cross-session continuity enabled
  - scoped writes by namespace
  - delete/export/tombstone propagation required
- Model strategy:
  - local-only by default
  - `gemma` default route, `lfm2` escalation route
  - no cloud dependency in MVP default profile

## Frontend rebuild sequence (A/B/C)

### Phase A - Foundation

- Build clean React app in Tauri v2
- Define typed websocket/event contracts
- Implement single state flow + single message send path
- Implement base shell: workspace pane, main conversation pane, inspector pane

Exit criteria:
- new app runs in Tauri
- no duplicate send path
- no legacy global mutable state dependency

### Phase B - Live Talk + Screen Assist

- Live talk:
  - push-to-talk
  - recording/transcribing/speaking/interrupted states
  - barge-in and hard-stop controls
  - transcript review for risky actions
- Screen assist:
  - screen/window/region selection
  - preview + annotation overlay
  - approval-gated action proposal queue

Exit criteria:
- daily-usable live voice loop
- policy-safe screen-assist flow

### Phase C - Hardening + Cutover

- Tauri least-privilege permissions + production CSP
- Safe-mode control center and memory controls as first-class UI
- Offline regression + websocket resilience gates
- Side-by-side soak; cut over; retire legacy frontend path

Exit criteria:
- new frontend is default production path
- security/reliability/performance gates pass

## Validation loop (required)

Run and track:

- Capability quality:
  - retrieval relevance (Recall@5, MRR@10)
  - model routing correctness under benchmark prompts
- Policy correctness:
  - approval required for high-risk actions
  - injection defenses block untrusted-triggered privileged actions
- Workflow durability:
  - cross-session memory continuation benchmark (target >= 90%)
  - offline regression suite pass for touched features
  - backup/restore drill checks against RPO/RTO targets

## Agent handoff contract

Every implementation handoff must include:

- Scope completed
  - files changed
  - behavior changed
- Validation performed
  - tests run
  - manual checks
- Open risks
  - known regressions/assumptions
- Next recommended step
  - one concrete action

## Completion criteria

The rebuild is complete when:

- new React/Tauri frontend is production default
- legacy frontend path is retired
- local-first runtime meets stability and SLO targets on Mac Air M4
- security controls, auditability, and safe-mode are operational
- memory continuity and offline reliability gates are consistently passing
