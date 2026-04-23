# Owlynn Linear Oversight Guide

Use this as your project "overseer" checklist so Linear stays actionable.

## Project-level details to maintain

- **Project summary**: one sentence mission and current phase.
- **Definition of done**: clear completion criteria for this phase.
- **Success metrics**: 2-4 measurable outcomes (e.g., tool-call success rate, bug MTTR).
- **Risk register**: top 3 risks and mitigation owner.
- **Scope guardrails**: what is explicitly out of scope right now.

## Issue quality standard

Every issue should include:

- **Why**: business or user impact.
- **What**: expected behavior and scope.
- **Acceptance criteria**: testable checklist.
- **Implementation notes**: key files/modules likely impacted.
- **Verification**: how to test manually/automatically.

## Labels to use consistently

- Type: `Bug`, `Feature`, `Plan`
- Domain: `MCP`, `runtime`, `frontend`, `backend`, `memory`, `tools`
- Priority signal: keep Linear priority aligned to real impact

## Weekly cadence (30 minutes)

1. Close stale issues with no current value.
2. Re-prioritize top 10 backlog items.
3. Ensure each in-progress issue has next concrete step.
4. Ensure each done issue has verification evidence in notes/PR.
5. Promote one future feature into a scoped plan item.

## Owlynn-specific dashboards to watch

- Bugs created this week vs bugs resolved this week
- In Progress aging (issues older than 7 days)
- MCP-related failures and startup reliability issues
- Feature throughput by week
