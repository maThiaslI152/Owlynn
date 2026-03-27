"""
Core Tools for the Local Cowork Agent.

File management, memory, and workspace tools.
No sandbox/container dependencies — runs natively.
"""

import os
from langchain_core.tools import tool
from ..memory.memory_manager import search_memories
from ..config.settings import WORKSPACE_DIR as _WORKSPACE_PATH
from .workspace_context import tool_workspace_root

BASE_WORKSPACE_DIR = str(_WORKSPACE_PATH.resolve())


def get_safe_workspace_path(filename: str) -> tuple[str, str | None]:
    """Resolve a path inside the active project workspace."""
    filename = filename.lstrip("/")
    if filename.startswith("workspace/"):
        filename = filename[len("workspace/"):]
    if filename.startswith("projects/"):
        workspace_root = BASE_WORKSPACE_DIR
    else:
        workspace_root = tool_workspace_root()

    filepath = os.path.abspath(os.path.join(workspace_root, filename))
    root_abs = os.path.abspath(workspace_root)
    base_abs = os.path.abspath(BASE_WORKSPACE_DIR)
    if not filepath.startswith(root_abs) or not filepath.startswith(base_abs):
        return "", "Error: Access denied. Path is outside workspace."
    return filepath, None


@tool
def read_workspace_file(filename: str) -> str:
    """Reads the content of a file in the workspace."""
    filepath, err = get_safe_workspace_path(filename)
    if err:
        return err
    if not os.path.exists(filepath):
        try:
            fn = os.path.basename(filepath)
            search_dir = os.path.dirname(filepath) or tool_workspace_root()
            matches = [f for f in os.listdir(search_dir) if fn in f or f in fn]
            if matches:
                filepath = os.path.join(search_dir, matches[0])
            else:
                return f"Error: File '{filename}' not found."
        except Exception:
            return f"Error: File '{filename}' not found."

    processed_dir = os.path.join(BASE_WORKSPACE_DIR, ".processed")
    fn_only = os.path.basename(filepath)
    cached_txt = os.path.join(processed_dir, fn_only + ".txt")
    cached_md = os.path.join(processed_dir, fn_only + ".md")

    try:
        if os.path.exists(cached_txt):
            with open(cached_txt, 'r', encoding='utf-8') as f:
                return f.read()
        elif os.path.exists(cached_md):
            with open(cached_md, 'r', encoding='utf-8') as f:
                return f.read()
        if filepath.lower().endswith(".pdf"):
            import fitz
            doc = fitz.open(filepath)
            text = "".join(page.get_text() + "\n\n" for page in doc)
            doc.close()
            return text if text.strip() else "This PDF has no extractable text layer."
        with open(filepath, 'r', encoding='utf-8') as f:
            return f.read()
    except Exception as e:
        return f"Error reading file {filename}: {e}"


@tool
def write_workspace_file(filename: str, content: str) -> str:
    """Writes content to a file in the workspace. Overwrites if it exists."""
    filepath, err = get_safe_workspace_path(filename)
    if err:
        return err
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    try:
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(content)
        return f"✅ Written to {filename}"
    except Exception as e:
        return f"Error writing file: {e}"


@tool
def edit_workspace_file(filename: str, search_pattern: str, replacement_text: str) -> str:
    """
    Search-and-replace in a workspace file. The search_pattern must match exactly.

    Args:
        filename: Path to the file.
        search_pattern: Exact text to find.
        replacement_text: Text to replace it with.
    """
    filepath, err = get_safe_workspace_path(filename)
    if err:
        return err
    if not os.path.exists(filepath):
        return f"Error: File '{filename}' not found."
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
        if search_pattern not in content:
            return f"Error: Pattern not found in {filename}."
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(content.replace(search_pattern, replacement_text))
        return f"✅ Updated {filename}"
    except Exception as e:
        return f"Error editing file: {e}"


@tool
def list_workspace_files(directory: str = ".") -> str:
    """Lists files in a workspace directory."""
    target_dir, err = get_safe_workspace_path(directory)
    if err:
        return err
    if not os.path.exists(target_dir):
        return f"Error: Directory '{directory}' not found."
    try:
        files = sorted(f for f in os.listdir(target_dir) if not f.startswith('.'))
        if not files:
            return "Directory is empty."
        lines = []
        for f in files:
            fp = os.path.join(target_dir, f)
            if os.path.isdir(fp):
                lines.append(f"📁 {f}/")
            else:
                size = os.path.getsize(fp)
                lines.append(f"📄 {f} ({size:,} bytes)")
        return "\n".join(lines)
    except Exception as e:
        return f"Error listing files: {e}"


@tool
def delete_workspace_file(filename: str) -> str:
    """Deletes a file from the workspace."""
    filepath, err = get_safe_workspace_path(filename)
    if err:
        return err
    if not os.path.exists(filepath):
        return f"Error: File '{filename}' not found."
    try:
        os.remove(filepath)
        return f"✅ Deleted {filename}"
    except Exception as e:
        return f"Error deleting file: {e}"


@tool
def recall_memories(query: str) -> str:
    """
    Searches long-term memory for facts about the user.

    Args:
        query: Topic or question to search for.
    """
    memories = search_memories(query, top_k=8)
    if not memories:
        return "No relevant memories found."
    lines = ["📋 Relevant memories:"]
    for m in memories:
        lines.append(f"  • {m['fact']}  [{m['timestamp'][:10]}]")
    return "\n".join(lines)
