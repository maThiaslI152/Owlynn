# AI Agent Navigation Index

This index is the fastest entry point for AI agents working in Owlynn.
Use it to locate the right source files, contracts, and tests before making changes.

## Current Delivery Status

- **Roadmap phase:** Phase 1 (Stabilization)
- **Phase 1 verdict:** Not passed yet
- **Reason:** Open stabilization risks remain in workspace/state regressions, cloud fallback safety hardening, router drift resilience, and CRUD/project-state invariants.

## Start Here By Task

### Routing and model behavior
- `src/agent/nodes/router.py`
- `src/agent/llm.py`
- `src/agent/swap_manager.py`
- `src/agent/nodes/complex.py`
- Tests:
  - `tests/test_router_model_swap.py`
  - `tests/test_router_properties.py`
  - `tests/test_llm_pool.py`
  - `tests/test_swap_manager.py`

### WebSocket/API contract work
- `src/api/server.py`
- `docs/CHAT_PROTOCOL.md`
- `docs/API_REFERENCE.md`
- Frontend consumer:
  - `frontend/script.js`
- Tests:
  - `tests/test_websocket_event_contract.py`
  - `tests/test_websocket_model_key_updates.py`
  - `tests/test_frontend_backend_alignment.py`

### Project/workspace state and CRUD
- `src/memory/project.py`
- `src/config/settings.py` (workspace roots and project path rules)
- `frontend/script.js`
- `frontend/modules/explorer.js`
- Tests:
  - `tests/test_crud_operations.py`
  - `tests/test_crud_properties.py`
  - `tests/test_project_context_isolation_properties.py`
  - `frontend/tests/project-state.property.test.js`
  - `frontend/tests/workspace-switching-integration.test.js`

### Cloud fallback and anonymization
- `src/agent/anonymization.py`
- `src/agent/nodes/complex.py`
- Tests:
  - `tests/test_cloud_fallback_anonymization_leak.py`
  - `tests/test_anonymization_properties.py`
  - `tests/test_complex_node_properties.py`

### Tooling and security gating
- `src/agent/tool_sets.py`
- `src/agent/nodes/security_proxy.py`
- `src/tools/`
- Docs:
  - `docs/TOOLS.md`

## Canonical Documentation Map

- Project overview and setup: `README.md`
- Full architecture and roadmap: `docs/PROJECT_DOCUMENTATION.md`
- Human workflow guide: `docs/HUMAN_PROJECT_GUIDE.md`
- AI execution guide: `docs/AI_AGENT_PROJECT_GUIDE.md`
- Rebuild canonical handoff: `docs/AI_REBUILD_MASTER_PLAN.md`
- Multi-agent resume protocol: `docs/AI_MULTI_AGENT_RESUME_PLAYBOOK.md`
- API contract: `docs/API_REFERENCE.md`
- WebSocket contract: `docs/CHAT_PROTOCOL.md`
- Active status and risks: `docs/STATUS.md`
- Architecture decisions: `docs/ADR.md`
- Linear workflow (issue/PR conventions): `docs/LINEAR_WORKFLOW.md`
- Performance & memory SLOs: `docs/PERFORMANCE_SLOS.md`

## Before You Commit (Agent Checklist)

1. Scope changes to one risk/theme.
2. Update tests in the touched area.
3. Verify behavior with targeted test runs.
4. Update docs when API/WS behavior changes.
5. Confirm `docs/STATUS.md` still reflects current risk state.
