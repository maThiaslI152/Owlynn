# Linear Workflow Guide

This document defines the convention for using Linear to track Owlynn development
work. Linear is the source of truth for work tracking (issues, milestones, projects).

## Linear Access

- **Team:** `Winter152` (key: `WIN`)
- **Project:** `Owlynn` (F65B0697-BCB6)
- **URL:** https://linear.app/winter152/project/owlynn-f65b0697bcb6

## Issue conventions

### Issue types

| Type | Prefix | When to use |
|------|--------|-------------|
| Feature | `WIN-*` | New capability (phase slice, new component, new endpoint) |
| Bug | `WIN-*` | Regression, unexpected behavior, crash |
| Chore | `WIN-*` | CI, tooling, docs, dependency updates |
| Spike | `WIN-*` | Research, exploration, prototype |

### Title format

```
<area>: <brief description>
```

Examples:
- `router: Add cloud-downgrade tracking to router_metadata`
- `frontend: Handle context_summarized WS event in App.tsx`
- `ci: Expand Python matrix to 3.13`

### Description format

```
## Goal

One paragraph describing what this issue achieves.

## Acceptance criteria

- [ ] Concrete, testable outcome 1
- [ ] Concrete, testable outcome 2

## Notes (optional)

Implementation hints, related files, known constraints.
```

### Labels

Use issue labels to categorize work:
- `frontend` — React/TypeScript/Tauri changes
- `backend` — Python/LangGraph/API changes
- `ci` — GitHub Actions, test infrastructure
- `docs` — Documentation-only changes
- `security` — Security proxy, permissions, audit
- `test` — Test additions or test infrastructure

## Milestones

Linked milestones track completed development phases:

| Milestone | Status |
|-----------|--------|
| Phase A-C: Frontend Rebuild & Hardening | Completed |
| Phase 1: Stabilization | Completed |
| Phase 2: Reliability & Visibility | Completed |
| Phase 3: Capability Expansion | In Progress |
| Phase 4: Governance & Release | In Progress |

## Branch naming

```
win-<issue-number>-<kebab-case-description>
```

Examples:
- `WIN-42-fix-ws-reconnect`
- `WIN-99-add-router-telemetry`

## Commit messages

When an issue exists, reference it in the commit body:

```
<subject>

Closes WIN-42.
```

## GitHub auto-linking

Pull request descriptions and commit messages with `WIN-*` patterns
automatically link to the corresponding Linear issue if the branch
follows the naming convention.

## Workflow

1. **Plan:** Create a Linear issue before starting work. Label it appropriately.
2. **Branch:** Create a branch using the `win-<number>-<description>` convention.
3. **Implement:** Keep changes scoped to the issue. Update tests and docs.
4. **Commit:** Reference the issue key (`WIN-*`) in commit messages.
5. **PR:** Create a pull request. The PR description should link to the issue.
6. **Close:** After merge, move the issue to "Done" in Linear.
