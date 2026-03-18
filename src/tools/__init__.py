from .web_tools import web_search
from .core_tools import execute_python_code, read_workspace_file, recall_memories

tool_registry = {
    "web_search":    web_search,
    "sandbox":       execute_python_code,
    "file_read":     read_workspace_file,
    "memory_search": recall_memories,
}
