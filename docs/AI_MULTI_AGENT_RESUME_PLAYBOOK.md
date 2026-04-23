# AI Multi-Agent Resume Playbook

## Purpose

This document enables any AI coding agent (Cursor, PearAI, Antigravity, and similar tools) to resume work on Owlynn with minimal context loss.

It defines:
- canonical status sources,
- current target architecture,
- handoff format,
- required validation and safety gates.

Canonical rebuild handoff document:
- `docs/AI_REBUILD_MASTER_PLAN.md`

## Project intent (current)

- Rebuild toward a **daily-use local desktop assistant** for Mac Air M4.
- Chosen desktop/frontend direction:
  - `Tauri v2` shell
  - `React + TypeScript` frontend rebuild from zero
- Runtime priorities:
  - realtime voice (STT/TTS, barge-in),
  - screen-assist UX,
  - strong system security controls,
  - uncensored cybersec/CTF response behavior,
  - persistent cross-session memory.

## Canonical source-of-truth documents

Read these first, in order:
1. `docs/STATUS.md`
2. `docs/AI_AGENT_INDEX.md`
3. `docs/AI_AGENT_PROJECT_GUIDE.md`
4. `docs/PROJECT_DOCUMENTATION.md`
5. `docs/ARCHITECTURE_OVERVIEW.md`
6. Active plan file in `.cursor/plans/` (if present)

If conflicts exist, prefer:
- `docs/STATUS.md` for current state
- active plan file for near-term implementation direction

## Active implementation plan file

- Primary plan path:
  - `.cursor/plans/reposition_local_ai_stack_23e757b5.plan.md`
- This plan is the current source for:
  - Tauri v2 + React clean-slate frontend rebuild
  - live-talk + screen-assist UX priorities
  - security/memory/recovery policies and acceptance gates

## Current architecture decisions (locked)

- Data stack:
  - `Redis` (session/hot state)
  - `Qdrant` (long-term memory vectors)
  - `SearxNG` (web retrieval)
- Model roles:
  - `gemma-4-e2b-heretic-uncensored-mlx` (fast path)
  - `lfm2-8b-a1b-absolute-heresy-mpoa-mlx` (big-brain escalation)
- Embedding baseline:
  - `text-embedding-nomic-embed-text-v1.5` pending benchmark lock
- Security stance:
  - no behavior/content filtering layer
  - strict tool permission and destructive-action controls

## Frontend migration decision

Legacy frontend (`frontend/index.html`, `frontend/script.js`, `frontend/modules`) is considered transitional.

Target:
- clean rebuild in a new frontend path (recommended `frontend-v2/`)
- React app with typed event contracts
- single state path + single message send path

## Delivery slices for frontend rebuild

- Slice A: foundation and shell
- Slice B: realtime voice and memory UX
- Slice C: screen assist, hardening, and cutover

Agent should preserve this sequence unless explicitly changed by user.

## Required safety and quality gates

Before marking work complete:
- security proxy / approval flow still enforced
- safe-mode UX remains operational
- no duplicate message send path
- state update path is single-source and test-covered
- offline regression subset passes for touched features

## Handoff packet format (required)

Every agent handoff should append/update a short section in its work note with:

- **Scope completed**
  - exact files changed
  - behavior changed
- **Validation performed**
  - tests run (names/commands)
  - manual checks done
- **Open risks**
  - known regressions, assumptions, TODOs
- **Next recommended step**
  - one concrete next action

Keep this concise and actionable.

## Resume checklist for new agent

1. Read canonical docs listed above.
2. Confirm current phase and active blockers from `docs/STATUS.md`.
3. Confirm if frontend work is in Slice A, B, or C.
4. Check for architecture drift against locked decisions in this document.
5. Execute only scoped work; avoid broad refactors outside current slice.
6. Update docs and handoff packet after any behavior/protocol change.

## Protocol and compatibility expectations

- Preserve compatibility with:
  - `docs/API_REFERENCE.md`
  - `docs/CHAT_PROTOCOL.md`
- If protocol changes are required:
  - update protocol docs in same work cycle,
  - include migration notes,
  - include frontend/backend compatibility notes.

## Notes for multi-agent ecosystems

This playbook is intentionally tool-agnostic.
Any agent framework can follow it as long as it can:
- read repository docs,
- run scoped tests,
- produce deterministic handoff notes.

If an external tool has its own memory/context layer, do not treat it as source-of-truth over repository docs.
