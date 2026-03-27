"""
Tool lists for the complex reasoning path.

Focused on general productivity: web search, file management,
document generation, task tracking, and skills.
"""

from src.tools.web_tools import web_search, fetch_webpage
from src.tools.core_tools import (
    read_workspace_file,
    write_workspace_file,
    edit_workspace_file,
    list_workspace_files,
    delete_workspace_file,
)
from src.tools.core_tools import recall_memories
from src.tools.doc_generator import create_docx, create_xlsx, create_pptx, create_pdf
from src.tools.notebook import notebook_run, notebook_reset
from src.tools.todo import todo_add, todo_list, todo_complete
from src.tools.ask_user import ask_user
from src.tools.skills import list_skills, invoke_skill

# Full tool set with web search enabled
COMPLEX_TOOLS_WITH_WEB: list = [
    # Web
    web_search,
    fetch_webpage,
    # File management
    read_workspace_file,
    write_workspace_file,
    edit_workspace_file,
    list_workspace_files,
    delete_workspace_file,
    # Memory
    recall_memories,
    # Computation
    notebook_run,
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
    # Skills
    list_skills,
    invoke_skill,
    # HITL
    ask_user,
]

# Tool set without web search
COMPLEX_TOOLS_NO_WEB: list = [
    read_workspace_file,
    write_workspace_file,
    edit_workspace_file,
    list_workspace_files,
    delete_workspace_file,
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
