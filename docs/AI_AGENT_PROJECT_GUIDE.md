# Owlynn Project Guide (AI Agent)

## Mission context

Owlynn is a local-first AI coworker. Prioritize reliability, traceability, and safe tool usage over
novelty. Keep changes explainable and compatible with local runtime constraints.

Quick navigation companion: `docs/AI_AGENT_INDEX.md`

## Architectural map

- `src/agent/`: routing, model selection, graph orchestration, security gating
- `src/api/`: HTTP + WebSocket app surface
- `src/tools/`: tool implementations exposed to agent
- `src/memory/`: persona/profile/project/user memory components
- `frontend/`: desktop UI shell and interaction modules
- `tests/`: behavior, property, and regression tests

## Execution rules for coding tasks

1. Keep diffs focused to the user request.
2. Preserve security proxy behavior around tool execution.
3. When touching routing/model behavior, update or add targeted tests.
4. Avoid mixing unrelated frontend/backend/docs changes in one commit.
5. Prefer deterministic fallbacks over silent failure paths.

## Model-routing expectations

- Router decides among simple, complex-default, vision, long-context, cloud.
- Complex node must preserve:
  - safe tool binding
  - fallback chain visibility
  - blank-response fallback behavior
  - anonymization/deanonymization correctness for cloud paths

## MCP + Linear guidance

- MCP servers are configured in `mcp_config.json`.
- MCP tools are loaded dynamically and should be available to complex tool flow.
- Linear is the source of truth for work tracking (`WIN-*`).
- Use issue-key conventions in branch names, commits, and PR metadata.
- Full Linear workflow conventions: `docs/LINEAR_WORKFLOW.md`

## Testing policy

- Minimum for model/routing changes:
  - `tests/test_llm_pool.py`
  - `tests/test_swap_manager.py`
  - `tests/test_router_web_intent.py`
- Add deeper coverage when touching:
  - anonymization (`tests/test_anonymization*.py`)
  - fallback behavior (`tests/test_complex_node_properties.py`)

## Definition of done for agent-authored changes

- Code compiles and tests pass for changed area.
- User-facing behavior is verified (or explicitly noted if not runnable).
- Documentation updated when behavior/workflow changes.
- Linear issue updated with summary and validation notes.
