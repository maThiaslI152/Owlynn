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
from ..memory.project import project_manager
from ..memory.long_term import memory as long_term_memory
from .mcp_client import get_mcp_tools

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
        # Fuzzy match fallback for model typos or variations (e.g., stripped numbering)
        try:
            filename_only = os.path.basename(filepath)
            all_files = os.listdir(WORKSPACE_DIR)
            # Find files where the requested name is a substring of the real file, or vice versa
            matches = [f for f in all_files if filename_only in f or f in filename_only]
            if matches:
                # Use the first best match found
                filepath = os.path.join(WORKSPACE_DIR, matches[0])
                print(f"[Workspace] Fuzzy matched '{filename_only}' to '{matches[0]}'")
            else:
                return f"Error: File '{filename}' not found in workspace."
        except Exception:
            return f"Error: File '{filename}' not found in workspace."

    
    processed_dir = os.path.join(WORKSPACE_DIR, ".processed")
    filename_only = os.path.basename(filepath)
    cached_txt = os.path.join(processed_dir, filename_only + ".txt")
    cached_md = os.path.join(processed_dir, filename_only + ".md")

    try:
        # 1. Check for pre-processed cache first
        if os.path.exists(cached_txt):
            with open(cached_txt, 'r', encoding='utf-8') as f:
                return f.read()
        elif os.path.exists(cached_md):
            with open(cached_md, 'r', encoding='utf-8') as f:
                return f.read()

        # 2. Fallback to on-the-fly processing (legacy support/race condition)
        if filepath.lower().endswith(".pdf"):
            import fitz
            doc = fitz.open(filepath)
            text = ""
            for page in doc:
                text += page.get_text() + "\n\n"
            doc.close()
            return text if text.strip() else "This PDF has no extractable text layer."

        # 3. Default text reading
        with open(filepath, 'r') as f:
            return f.read()

    except Exception as e:
        return f"Error reading file {filename}: {str(e)}"

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
def list_workspace_files(directory: str = ".", recursive: bool = False) -> str:
    """
    Lists files in the workspace. Use recursive=True for a tree view.
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
        if recursive:
            # Simple recursive listing (equivalent to get_file_tree)
            find_cmd = f"find {directory} -maxdepth 3 -not -path '*/.*' -not -path '*/__pycache__*'"
            result = sandbox.execute_shell(find_cmd)
            if not result or "Execution Error" in result:
                return f"Error listing recursive files in {directory}."
            lines = sorted([l for l in result.splitlines() if l.strip()])
            return "📁 Workspace Tree:\n" + "\n".join(lines)
        else:
            files = os.listdir(target_dir)
            files = sorted([f for f in files if not f.startswith('.')])
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
    
    Pre-installed libraries include: matplotlib, pandas, numpy, scipy, seaborn.
    Any files saved by your script will appear in the workspace folder.
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

@tool
def search_workspace_files(query: str, recursive: bool = True) -> str:
    """
    Searches for a specific text string or regex pattern within files in the workspace.
    Returns a list of matching lines and their filenames.
    
    Args:
        query: The string or regex pattern to search for.
        recursive: Whether to search recursively through subdirectories.
    """
    # Use grep in the sandbox for efficient searching
    grep_cmd = f"grep -rn{'r' if recursive else ''} --exclude-dir='.git' --exclude-dir='.venv' \"{query}\" ."
    result = sandbox.execute_shell(grep_cmd)
    
    if not result.strip():
        return f"No matches found for: \"{query}\""
    
    # Cap result length to avoid context overflow
    if len(result) > 4000:
        result = result[:4000] + "\n\n... [search results truncated]"
        
    return f"🔍 Search results for: \"{query}\":\n\n{result}"


@tool
def edit_workspace_file(filename: str, search_pattern: str, replacement_text: str) -> str:
    """
    Performs a targeted search-and-replace on a specific file in the workspace.
    This is more efficient than `write_workspace_file` for large files.
    The search_pattern must match EXACTLY (including whitespace) to be replaced.
    
    Args:
        filename: The path to the file to edit.
        search_pattern: The exact block of text to find.
        replacement_text: The new text to replace it with.
    """
    filename = filename.lstrip("/")
    if filename.startswith("workspace/"):
        filename = filename[len("workspace/"):]
        
    filepath = os.path.join(WORKSPACE_DIR, filename)
    if not os.path.exists(filepath):
        return f"Error: File '{filename}' not found."
        
    try:
        with open(filepath, 'r') as f:
            content = f.read()
            
        if search_pattern not in content:
            return f"Error: Could not find exact search pattern in {filename}. Ensure whitespace matches exactly."
            
        new_content = content.replace(search_pattern, replacement_text)
        with open(filepath, 'w') as f:
            f.write(new_content)
            
        return f"✅ Successfully updated {filename} (replaced 1 occurrence)."
    except Exception as e:
        return f"Error editing file: {str(e)}"

@tool
def delete_workspace_file(filename: str) -> str:
    """
    Deletes a file from the agent's workspace.
    """
    filename = filename.lstrip("/")
    if filename.startswith("workspace/"):
        filename = filename[len("workspace/"):]
        
    filepath = os.path.join(WORKSPACE_DIR, filename)
    if not os.path.exists(filepath):
        return f"Error: File '{filename}' not found."
        
    try:
        os.remove(filepath)
        return f"Successfully deleted {filename}"
    except Exception as e:
        return f"Error deleting file: {str(e)}"

@tool
def create_directory(directory: str) -> str:
    """
    Creates a new directory in the workspace.
    """
    directory = directory.lstrip("/")
    if directory.startswith("workspace/"):
        directory = directory[len("workspace/"):]
        
    target_dir = os.path.join(WORKSPACE_DIR, directory)
    try:
        os.makedirs(target_dir, exist_ok=True)
        return f"Successfully created directory: {directory}"
    except Exception as e:
        return f"Error creating directory: {str(e)}"

@tool
def get_current_time() -> str:
    """
    Returns the current local date and time.
    """
    from datetime import datetime
    now = datetime.now()
    return f"🕒 Current Date and Time: {now.strftime('%A, %B %d, %Y %I:%M %p')}"

@tool
def get_workspace_stats() -> str:
    """
    Returns a summary of the workspace content (total files, size).
    """
    total_files = 0
    total_size = 0
    
    for root, dirs, files in os.walk(WORKSPACE_DIR):
        # Skip hidden files/dirs
        files = [f for f in files if not f.startswith('.')]
        dirs[:] = [d for d in dirs if not d.startswith('.')]
        
        for f in files:
            fp = os.path.join(root, f)
            total_files += 1
            total_size += os.path.getsize(fp)
            
    # Format size
    for unit in ['B', 'KB', 'MB', 'GB']:
        if total_size < 1024:
            size_str = f"{total_size:.2f} {unit}"
            break
        total_size /= 1024
    else:
        size_str = f"{total_size:.2f} TB"
        
    return f"📊 Workspace Stats:\n- Total Files: {total_files}\n- Total Size: {size_str}"

# ─── Project Management Tools ───────────────────────────────────────────────

@tool
def list_projects() -> str:
    """
    Lists all available projects in the Local Cowork platform.
    """
    projects = project_manager.list_projects()
    if not projects:
        return "No projects found."
    
    lines = ["📂 Available Projects:"]
    for p in projects:
        lines.append(f"  • {p['name']} (ID: {p['id']})")
    return "\n".join(lines)

@tool
def get_project_info(project_id: str) -> str:
    """
    Retrieves detailed information about a specific project, 
    including its instructions and registered knowledge base files.
    """
    project = project_manager.get_project(project_id)
    if not project:
        return f"Error: Project ID '{project_id}' not found."
    
    info = [
        f"📁 Project: {project['name']} (ID: {project['id']})",
        f"📝 Instructions: {project.get('instructions', 'None')}",
        "📄 Knowledge Base Files:"
    ]
    
    files = project.get("files", [])
    if not files:
        info.append("  (No files registered)")
    for f in files:
        info.append(f"  • {f['name']} ({f['type']})")
        
    return "\n".join(info)

@tool
def search_project_knowledge(query: str, project_id: str = "default") -> str:
    """
    Searches the long-term knowledge base (vector memory) for a specific project.
    Use this to find specific information previously stored in a project's knowledge base.
    """
    try:
        results_dict = long_term_memory.search(query, user_id=project_id, limit=8)
        results = results_dict.get("results", []) if isinstance(results_dict, dict) else results_dict
        
        if not results:
            return f"No relevant knowledge found for '{query}' in project '{project_id}'."
        
        lines = [f"🧠 Knowledge Search Results for: \"{query}\" (Project: {project_id}):"]
        for r in results:
            lines.append(f"  • {r['memory']}")
        return "\n".join(lines)
    except Exception as e:
        return f"Error searching project knowledge: {str(e)}"

@tool
def list_available_mcp_tools() -> str:
    """
    Lists all externally connected MCP (Model Context Protocol) tools.
    These tools are provided by external servers and can extend the agent's capabilities.
    """
    mcp_tools = get_mcp_tools()
    if not mcp_tools:
        return "No external MCP tools are currently connected."
    
    lines = ["🛠️ Connected MCP Tools:"]
    for t in mcp_tools:
        lines.append(f"  • {t.name}: {t.description[:100]}...")
    return "\n".join(lines)

@tool
async def add_to_knowledge_base(name: str, content: str, project_id: str = "default") -> str:
    """
    Adds a piece of text or a document to a project's permanent knowledge base.
    This content will be indexed and available for future retrieval via RAG.
    
    Args:
        name: A descriptive name for the knowledge piece (e.g. 'Project Requirements').
        content: The actual text content to store.
        project_id: The ID of the project to add this to.
    """
    try:
        await project_manager.add_knowledge(project_id, name, content)
        return f"✅ Successfully added '{name}' to knowledge base of project '{project_id}'."
    except Exception as e:
        return f"Error adding to knowledge base: {str(e)}"

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
    search_workspace_files,
    edit_workspace_file,
    delete_workspace_file,
    create_directory,
    get_workspace_stats,
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
    get_current_time,
    # Project & MCP tools
    list_projects,
    get_project_info,
    search_project_knowledge,
    list_available_mcp_tools,
    add_to_knowledge_base,
]
