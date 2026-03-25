from .web_tools import web_search, fetch_webpage
from .core_tools import execute_python_code, read_workspace_file, recall_memories

tool_registry = {
    "web_search": web_search,
    "fetch_webpage": fetch_webpage,
    "sandbox": execute_python_code,
    "file_read": read_workspace_file,
    "memory_search": recall_memories,
}
