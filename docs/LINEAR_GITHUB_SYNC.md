# Linear <-> GitHub Sync (Owlynn)

This repository uses Linear issue keys to connect GitHub branches/commits/PRs with Linear issues.

## Current state

- Owlynn can access Linear via MCP tools.
- Automatic GitHub linkage is provided by Linear's native GitHub integration.
- This repo now includes conventions/templates to keep linkage reliable.

## One-time setup (Linear UI)

1. In Linear, open `Settings -> Integrations -> GitHub`.
2. Connect the GitHub account/organization that owns this repository.
3. Enable access to the Owlynn repository.
4. Confirm auto-linking is enabled for branch names, commit messages, and PR titles/bodies.

## Required repo conventions

- Branch name includes issue key:
  - `WIN-7-linear-command-surface`
- Commit message includes issue key:
  - `feat(chat): add linear command parser (WIN-7)`
- PR title/body includes issue key:
  - Title: `[WIN-7] Add Linear command parser`
  - Body: `Linear: WIN-7`

## Local git warnings

This repo includes a non-blocking commit hook to warn when both branch and commit
message are missing a `WIN-*` key.

Install once per clone:

```bash
bash scripts/install-git-hooks.sh
```

Terminal-to-Linear bug reporter:

```bash
LINEAR_API_KEY=lin_api_xxx python3 scripts/terminal_to_linear.py
```

## Verify sync works

1. Create a test branch with a valid key (e.g. `WIN-5-test-sync`).
2. Open a PR that includes the same key.
3. In Linear issue `WIN-5`, confirm branch/PR appears in the issue's development section.

## Troubleshooting

- If links do not appear, verify:
  - Repository is enabled in Linear GitHub integration.
  - The same issue key exists in branch and PR text.
  - The key matches team prefix exactly (e.g. `WIN-7`).
