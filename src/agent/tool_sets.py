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


# ─── Dynamic Tool Loading: Toolbox Registry ─────────────────────────────
TOOLBOX_REGISTRY: dict[str, list] = {
    "web_search": [web_search, fetch_webpage],
    "file_ops": [read_workspace_file, write_workspace_file, edit_workspace_file,
                 list_workspace_files, delete_workspace_file],
    "data_viz": [create_docx, create_xlsx, create_pptx, create_pdf,
                 notebook_run, notebook_reset],
    "productivity": [todo_add, todo_list, todo_complete, list_skills, invoke_skill],
    "memory": [recall_memories],
}

ALWAYS_INCLUDED_TOOLS: list = [ask_user]


def resolve_tools(toolbox_names: list[str], web_search_enabled: bool = True) -> list:
    """
    Return the union of tools from requested toolboxes + always-included tools.

    - "all" in toolbox_names → full tool set (equivalent to COMPLEX_TOOLS_WITH_WEB/NO_WEB)
    - web_search_enabled=False → exclude web_search toolbox tools even if requested
    - ask_user is always included regardless of selection
    """
    if not toolbox_names or "all" in toolbox_names:
        base = list(COMPLEX_TOOLS_WITH_WEB if web_search_enabled else COMPLEX_TOOLS_NO_WEB)
        # Ensure ask_user is present
        for t in ALWAYS_INCLUDED_TOOLS:
            if t not in base:
                base.append(t)
        return base

    tools: list = []
    seen_ids: set = set()
    for name in toolbox_names:
        if name == "web_search" and not web_search_enabled:
            continue
        if name in TOOLBOX_REGISTRY:
            for t in TOOLBOX_REGISTRY[name]:
                tid = id(t)
                if tid not in seen_ids:
                    seen_ids.add(tid)
                    tools.append(t)

    # Always include ask_user
    for t in ALWAYS_INCLUDED_TOOLS:
        if id(t) not in seen_ids:
            seen_ids.add(id(t))
            tools.append(t)

    return tools
