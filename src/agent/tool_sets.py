"""
Tool lists for the complex reasoning path.

Keep the LLM-bound set small (≤10 tools) to avoid context overflow on local models.
Additional tools are available in CORE_TOOLS but not bound to the LLM by default.
"""

from src.tools import (
    web_search,
    fetch_webpage,
    execute_python_code,
    read_workspace_file,
    recall_memories,
)
from src.tools.notebook import notebook_run
from src.tools.todo import todo_add, todo_list
from src.tools.ask_user import ask_user

# Primary tools bound to the LLM (kept small for local model context limits)
COMPLEX_TOOLS_WITH_WEB: list = [
    web_search,
    fetch_webpage,
    read_workspace_file,
    execute_python_code,
    recall_memories,
    notebook_run,
    todo_add,
    todo_list,
    ask_user,
]

COMPLEX_TOOLS_NO_WEB: list = [
    read_workspace_file,
    execute_python_code,
    recall_memories,
    notebook_run,
    todo_add,
    todo_list,
    ask_user,
]

# Extended tools available via invoke_skill or direct call but NOT bound to LLM
# (avoids bloating the tool schema sent to the model)
try:
    from src.tools.doc_generator import create_docx, create_xlsx, create_pptx, create_pdf
    from src.tools.notebook import notebook_vars, notebook_reset
    from src.tools.todo import todo_complete, todo_remove
    from src.tools.skills import list_skills, invoke_skill

    EXTENDED_TOOLS: list = [
        create_docx, create_xlsx, create_pptx, create_pdf,
        notebook_vars, notebook_reset,
        todo_complete, todo_remove,
        list_skills, invoke_skill,
    ]
except ImportError:
    EXTENDED_TOOLS = []
