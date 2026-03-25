"""Tool lists for the complex reasoning path (keep binding and ToolNode in sync)."""

from src.tools import (
    web_search,
    fetch_webpage,
    execute_python_code,
    read_workspace_file,
    recall_memories,
)

# Order matches historical llm.py binding for OpenAI-compatible servers.
COMPLEX_TOOLS_WITH_WEB: list = [
    web_search,
    fetch_webpage,
    execute_python_code,
    read_workspace_file,
    recall_memories,
]

COMPLEX_TOOLS_NO_WEB: list = [
    execute_python_code,
    read_workspace_file,
    recall_memories,
]
