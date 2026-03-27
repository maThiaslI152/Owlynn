"""Tool lists for the complex reasoning path (keep binding and ToolNode in sync)."""

from src.tools import (
    web_search,
    fetch_webpage,
    execute_python_code,
    read_workspace_file,
    recall_memories,
)
from src.tools.doc_generator import create_docx, create_xlsx, create_pptx, create_pdf
from src.tools.notebook import notebook_run, notebook_vars, notebook_reset
from src.tools.todo import todo_add, todo_list, todo_complete, todo_remove
from src.tools.ask_user import ask_user
from src.tools.skills import list_skills, invoke_skill

# Full tool set with web search enabled
COMPLEX_TOOLS_WITH_WEB: list = [
    # Web
    web_search,
    fetch_webpage,
    # Workspace
    read_workspace_file,
    execute_python_code,
    # Memory
    recall_memories,
    # Notebook (stateful REPL)
    notebook_run,
    notebook_vars,
    notebook_reset,
    # Document generation
    create_docx,
    create_xlsx,
    create_pptx,
    create_pdf,
    # Task tracking
    todo_add,
    todo_list,
    todo_complete,
    todo_remove,
    # Skills
    list_skills,
    invoke_skill,
    # HITL
    ask_user,
]

# Tool set without web search
COMPLEX_TOOLS_NO_WEB: list = [
    # Workspace
    read_workspace_file,
    execute_python_code,
    # Memory
    recall_memories,
    # Notebook (stateful REPL)
    notebook_run,
    notebook_vars,
    notebook_reset,
    # Document generation
    create_docx,
    create_xlsx,
    create_pptx,
    create_pdf,
    # Task tracking
    todo_add,
    todo_list,
    todo_complete,
    todo_remove,
    # Skills
    list_skills,
    invoke_skill,
    # HITL
    ask_user,
]
