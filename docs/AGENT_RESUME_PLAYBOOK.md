# Agent Resume Playbook

## Purpose

This document allows any AI coding assistant (Cursor, PearAI, Antigravity, or others) to resume work on the rebuild with minimal context loss.

## Project Direction (Locked)

- Desktop shell: `Tauri v2`
- Frontend: `React + TypeScript` (clean rebuild from zero)
- Core modes:
  - Live Talk Mode (realtime voice)
  - Work Mode (full productivity layout)
  - Screen Assist Mode (capture + action proposals)
- Data stack: `Redis + Qdrant + SearxNG`
- Models:
  - fast: `gemma-4-e2b-heretic-uncensored-mlx`
  - reasoning: `lfm2-8b-a1b-absolute-heresy-mpoa-mlx`

## Current Rebuild Slices

- Phase A: Foundation (shell, typed contracts, unified send/state path)
- Phase B: Realtime interactions (voice + screen assist + approvals)
- Phase C: Hardening/migration (security, offline tests, legacy retirement)

## Non-Negotiable Constraints

- Fully local-first operation on Mac Air M4
- High security on tool execution and destructive actions
- No behavioral content filtering requirement for cybersec/CTF use
- Cross-session memory continuity is required
- Safe mode must support reasoning-only incident operation

## Resume Protocol (Every Agent Session)

1. Read this file first.
2. Read `docs/STATUS.md` and align with active reality.
3. Confirm active phase (A, B, or C) and choose one concrete objective.
4. Execute only tasks that map to current phase acceptance criteria.
5. Update this file before ending session:
   - last updated timestamp,
   - what changed,
   - current blockers,
   - next 3 actions.

## Session Handoff Template

### Last Updated

- Date:
- Agent:
- Mode (plan/execute):

### Completed This Session

- Item 1:
- Item 2:
- Item 3:

### Current Phase Status

- Active phase:
- Acceptance checks passed:
- Remaining checks:

### Blockers

- Blocker:
  - Impact:
  - Unblock condition:

### Next 3 Actions

1.
2.
3.

## Decision Logging Rule

Any major architecture or security decision must also be added to `docs/DECISIONS.md` with:

- date,
- decision statement,
- rationale,
- alternatives considered,
- rollback plan.
