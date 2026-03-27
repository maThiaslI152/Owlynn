"""
Tool lists for the complex reasoning path.

The 9B Qwen model handles ~15 tools fine within 8192 context.
Keep descriptions concise to minimize token overhead.
"""

from src.tools import (
    web_search,
    fetch_webpage,
    execute_python_code,
    read_workspace_file,
    recall_memories,
)
from src.tools.doc_generator import create_docx, create_xlsx, create_pptx, create_pdf
from src.tools.notebook import notebook_run, notebook_reset
from src.tools.todo import todo_add, todo_list, todo_complete
from src.tools.ask_user import ask_user
from src.tools.skills import list_skills, invoke_skill

# Full tool set with web search enabled
COMPLEX_TOOLS_WITH_WEB: list = [
    web_search,
    fetch_webpage,
    read_workspace_file,
    execute_python_code,
    recall_memories,
    notebook_run,
    notebook_reset,
    create_docx,
    create_xlsx,
    create_pptx,
    create_pdf,
    todo_add,
    todo_list,
    todo_complete,
    list_skills,
    invoke_skill,
    ask_user,
]

# Tool set without web search
COMPLEX_TOOLS_NO_WEB: list = [
    read_workspace_file,
    execute_python_code,
    recall_memories,
    notebook_run,
    notebook_reset,
    create_docx,
    create_xlsx,
    create_pptx,
    create_pdf,
    todo_add,
    todo_list,
    todo_complete,
    list_skills,
    invoke_skill,
    ask_user,
]
