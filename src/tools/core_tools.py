"""
Core Native Tools for the Local Cowork Agent.

This module defines the primary tools available to the agent for managing
files, executing code, updating profile/persona, and performing searches.
All tools are wrapped using @tool for LangChain integration.
"""

import os
from langchain_core.tools import tool
from .sandbox import PodmanSandbox
from .thai_translation_tool import lookup_thai_terms
from .web_tools import web_search, fetch_webpage
from ..memory.user_profile import get_profile, update_profile
from ..memory.memory_manager import save_memory, search_memories
from ..memory.persona import get_persona, update_persona_field

# Initialize the global sandbox instance
# Assuming the script is run from the project root (/Users/tim/Documents/Owlynn)
WORKSPACE_DIR = os.path.abspath(os.path.join(os.getcwd(), "workspace"))
sandbox = PodmanSandbox(workspace_path=WORKSPACE_DIR)

@tool
def execute_sandboxed_shell(command: str) -> str:
    """
    Executes a bash shell command inside a secure Podman sandbox container.
    Use this to install dependencies, run code, or manipulate files in the workspace.
    The workspace is mounted at `/workspace` inside the container.
    """
    return sandbox.execute_shell(command)

@tool
def read_workspace_file(filename: str) -> str:
    """
    Reads the content of a file located in the agent's workspace.
    """
    # Strip leading slash to prevent os.path.join from treating it as absolute root
    filename = filename.lstrip("/")
    # Also strip the literal '/workspace' if the agent uses its internal path
    if filename.startswith("workspace/"):
        filename = filename[len("workspace/"):]
        
    filepath = os.path.join(WORKSPACE_DIR, filename)
    if not os.path.exists(filepath):
        return f"Error: File '{filename}' not found in workspace."
    
    try:
        with open(filepath, 'r') as f:
            return f.read()
    except Exception as e:
        return f"Error reading file: {str(e)}"

@tool
def write_workspace_file(filename: str, content: str) -> str:
    """
    Writes content to a specific file in the agent's workspace.
    Will overwrite the file if it already exists.
    """
    filename = filename.lstrip("/")
    if filename.startswith("workspace/"):
        filename = filename[len("workspace/"):]
        
    filepath = os.path.join(WORKSPACE_DIR, filename)
    
    # Ensure subdirectory exists if passed (e.g., 'src/main.py')
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    
    try:
        with open(filepath, 'w') as f:
            f.write(content)
        return f"Successfully written to {filename}"
    except Exception as e:
        return f"Error writing file: {str(e)}"

@tool
def list_workspace_files(directory: str = ".") -> str:
    """
    Lists all files in the given directory of the workspace.
    """
    directory = directory.lstrip("/")
    if directory.startswith("workspace/") or directory == "workspace":
        directory = directory[len("workspace"):].lstrip("/")
        if not directory:
             directory = "."
             
    target_dir = os.path.join(WORKSPACE_DIR, directory)
    if not os.path.exists(target_dir):
        return f"Error: Directory '{directory}' not found."
        
    try:
        files = os.listdir(target_dir)
        if not files:
            return "Directory is empty."
        return "\n".join(files)
    except Exception as e:
        return f"Error listing files: {str(e)}"

@tool
def execute_python_code(code: str) -> str:
    """
    Executes a block of Python code directly inside the sandbox container.
    Use this for running Python scripts instead of `execute_sandboxed_shell`.
    """
    import uuid
    filename = f".temp_{uuid.uuid4().hex[:8]}.py"
    filepath = os.path.join(WORKSPACE_DIR, filename)
    try:
        with open(filepath, 'w') as f:
            f.write(code)
    except Exception as e:
        return f"Error writing temporary python file: {str(e)}"
    
    # Run the script in the sandbox
    result = sandbox.execute_shell(f"python {filename}")
    
    # Clean up
    try:
        os.remove(filepath)
    except:
        pass
        
    return result

# ─── Memory & Persona Tools ─────────────────────────────────────────────────

@tool
def update_user_profile(field: str, value: str) -> str:
    """
    Updates the user's profile with a new preference or personal detail.
    Use this when the user tells you their name, preferred language,
    education level, domains of interest, or response style.

    Valid fields: name, preferred_language (e.g. 'th', 'en'),
                  education_level, domains_of_interest (comma-separated), response_style.

    Args:
        field: The profile field to update.
        value: The new value for that field.
    """
    try:
        updated = update_profile(field, value)
        return f"✅ Profile updated: {field} = {updated[field]}"
    except Exception as e:
        return f"[update_user_profile] Error: {e}"


@tool
def remember_fact(fact: str) -> str:
    """
    Saves an important fact about the user or their preferences to long-term memory.
    Call this whenever the user shares something worth remembering across sessions,
    e.g. 'I prefer Thai responses', 'I am studying cybersecurity', 'My name is Tim'.

    Args:
        fact: A concise factual statement to remember.
    """
    return save_memory(fact)


@tool
def recall_memories(query: str) -> str:
    """
    Searches long-term memory for facts related to a query.
    Use this to check if you already know something about the user or their preferences.

    Args:
        query: A topic or question to search memories for.
    """
    memories = search_memories(query, top_k=8)
    if not memories:
        return "No relevant memories found."
    lines = ["📋 Relevant memories:"]
    for m in memories:
        lines.append(f"  • {m['fact']}  [{m['timestamp'][:10]}]")
    return "\n".join(lines)


@tool
def update_persona(field: str, value: str) -> str:
    """
    Updates the agent's persona (name, role, tone, or language preference).
    Call this when the user asks you to change your name, be more formal/casual,
    or adjust any aspect of your personality.

    Valid fields: name, role, tone, language_preference.

    Args:
        field: The persona field to update.
        value: The new value.
    """
    try:
        updated = update_persona_field(field, value)
        return f"✅ Persona updated: {field} = {updated[field]}"
    except Exception as e:
        return f"[update_persona] Error: {e}"


# The list of all LangChain tools available to the agent
CORE_TOOLS = [
    execute_sandboxed_shell,
    read_workspace_file,
    write_workspace_file,
    list_workspace_files,
    execute_python_code,
    # RAG Thai translation
    lookup_thai_terms,
    # Web tools
    web_search,
    fetch_webpage,
    # Memory & persona tools
    update_user_profile,
    remember_fact,
    recall_memories,
    update_persona,
]
