#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HOOKS_DIR="${REPO_ROOT}/.githooks"

if [[ ! -d "${HOOKS_DIR}" ]]; then
  echo "Error: ${HOOKS_DIR} not found."
  exit 1
fi

chmod +x "${HOOKS_DIR}/commit-msg"
git -C "${REPO_ROOT}" config core.hooksPath .githooks

echo "Installed repo-local git hooks."
echo "core.hooksPath -> .githooks"
echo "Active hook: .githooks/commit-msg (non-blocking WIN-* warning)"
