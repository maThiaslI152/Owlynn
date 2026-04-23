# Owlynn Status

Last updated: 2026-04-23

## Current Progress

- Core LangGraph flow is active: memory inject, routing, complex tool loop, and memory writeback.
- Hybrid model routing (small/medium/cloud) and medium-model swap logic are implemented.
- Security proxy with HITL approval is in place for sensitive tools.
- Backend API + WebSocket chat and Tauri frontend shell are integrated.
- Test coverage includes unit, integration, and property-based suites across backend and frontend.

## Current Bugs / Risks

- Workspace switching can still cause stale UI state in edge transitions.
- Frontend/backend event payload mismatches can surface in integration paths.
- Cloud fallback + anonymization paths require continued regression protection.
- Router selection may drift on borderline prompts or long-context/tool-heavy prompts.
- CRUD and project-state invariants need continued hardening under repeated operations.

## Next Plan

- Finish frontend module stabilization and remove remaining legacy overlap.
- Close workspace/project-state regressions with deterministic integration tests.
- Complete summarize-node routing and persistence flow.
- Improve route/fallback observability and tool execution diagnostics.

## Roadmap (Phased)

### Phase 1: Stabilization
- Resolve workspace/state regressions.
- Finalize modular frontend parity and cleanup.
- Lock anonymization/fallback safety with tests.

### Phase 2: Reliability & Visibility
- Add route and fallback telemetry.
- Strengthen API/WS contract tests and error-handling UX.
- Standardize CI gates for critical integration/property suites.

### Phase 3: Capability Expansion
- Enhance summarize/context compression behavior.
- Expand project vault and knowledge map continuity features.
- Improve orchestration controls in frontend UX.

### Phase 4: Governance & Release
- Introduce documentation versioning and architecture decisions log.
- Align release train with Linear milestones.
- Define performance and memory SLOs for local-first operation.
