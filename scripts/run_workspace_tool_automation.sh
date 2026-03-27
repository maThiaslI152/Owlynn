#!/usr/bin/env bash
# Run workspace / read_workspace_file automation (no live LLM).
# Optional live LLM probe: RUN_LLM_INTEGRATION=1 ./scripts/run_workspace_tool_automation.sh
set -euo pipefail
cd "$(dirname "$0")/.."
if [[ -f .venv/bin/activate ]]; then
  # shellcheck source=/dev/null
  source .venv/bin/activate
fi
exec python3 -m pytest tests/test_workspace_tool_automation.py -q --tb=short "$@"
