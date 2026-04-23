# AI Multi-Agent Frontend Rebuild Plan

## Purpose

This document is the shared handoff plan for multiple AI agents (Cursor, Antigravity, PearAI, and others) to continue the same rebuild work without losing context.

Primary objective:
- Rebuild the desktop frontend from zero using `Tauri v2 + React + TypeScript`.
- Keep backend orchestration local-first and security-focused.
- Deliver a dynamic, small, sleek UX for live talk and realtime screen assist.

## Canonical Source of Truth

- Active planning file:
  - `/Users/tim/.cursor/plans/reposition_local_ai_stack_23e757b5.plan.md`
- Current status references:
  - `docs/STATUS.md`
  - `docs/AI_AGENT_INDEX.md`

When this file conflicts with `STATUS.md`, resolve drift first and then update both.

## Locked Architectural Decisions

- Desktop shell: `Tauri v2`.
- Frontend: `React + TypeScript` rebuild from zero.
- Data stack: `Redis + Qdrant + SearxNG`.
- Memory requirement: strong cross-session continuity by default.
- Security model:
  - no behavioral content filtering for cybersec/CTF responses,
  - strict tool permissioning, destructive-action confirmation, and auditability.

## Execution Slices

### Slice A - Foundation

- Create new frontend app structure (do not extend old monolith):
  - `app-shell`, `live-talk`, `work-mode`, `screen-assist`, `memory`, `safe-mode`, `ws-client`, `settings`.
- Build typed websocket transport client and single action dispatcher.
- Build one canonical message submit path.
- Implement base shell layout and connection state UX.

Definition of done:
- App runs in Tauri.
- No duplicate send path.
- No global mutable state fallbacks.

### Slice B - Live Talk + Screen Assist

- Implement live-talk UX:
  - push-to-talk,
  - voice state machine,
  - barge-in + hard stop,
  - transcript preview for risky actions.
- Implement screen-assist UX:
  - screen/window/region capture select,
  - preview + annotation overlay,
  - approval-gated action proposals.
- Add TTS controls and latency indicators.

Definition of done:
- Stable daily live-talk flow.
- Screen-assist useful for real work and policy-safe.

### Slice C - Hardening + Cutover

- Apply least-privilege Tauri permissions and production CSP.
- Add safe-mode control center and memory controls in primary UI.
- Enforce offline regression suite and websocket resilience tests.
- Run soak period and cut over to new frontend.
- Retire legacy frontend path after acceptance gates pass.

Definition of done:
- New frontend is production default.
- Legacy path decommissioned.

## Agent Handoff Protocol

Any agent resuming this work must do the following before changing scope:

1. Read:
   - `docs/STATUS.md`
   - `docs/AI_AGENT_INDEX.md`
   - `/Users/tim/.cursor/plans/reposition_local_ai_stack_23e757b5.plan.md`
   - this file
2. Confirm active slice (`A`, `B`, or `C`) and open tasks.
3. Append concise status notes to `docs/STATUS.md` after each substantial milestone.
4. Preserve these invariants:
   - one canonical send pipeline,
   - single-source frontend state,
   - explicit safe-mode UX,
   - auditable high-risk actions.

## Non-Negotiable Acceptance Gates

- Cross-session memory continuity benchmark >= 90%.
- High-risk tool actions always require explicit confirmation.
- Prompt-injection tool-layer tests pass with zero silent bypasses.
- Offline regression suite passes on Mac Air M4 profile.
- Voice SLO targets hold in balanced full-duplex mode.

## Suggested Next Action for Resuming Agents

Start with **Slice A**, create the new frontend skeleton and typed transport contracts, then freeze interface contracts before implementing voice and screen-assist interactions.
