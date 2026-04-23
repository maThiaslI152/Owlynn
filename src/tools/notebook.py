"""
Notebook Tool — Stateful Python REPL that persists variables across cells.
Mirrors Cowork's Notebook tool for iterative data exploration.

Unlike execute_python_code (fire-and-forget sandbox), this keeps state
in-process so variables, imports, and DataFrames survive between calls.
"""

import io
import sys
import traceback
import threading
from contextlib import redirect_stdout, redirect_stderr
from langchain_core.tools import tool

# Per-thread notebook state to prevent cross-session contamination
# when multiple users share the same server process.
_notebook_lock = threading.Lock()
_notebook_sessions: dict[int, dict] = {}  # thread_id -> {"globals": dict, "counter": int}


def _get_session() -> dict:
    """Get or create the notebook session for the current thread."""
    tid = threading.get_ident()
    with _notebook_lock:
        if tid not in _notebook_sessions:
            _notebook_sessions[tid] = {"globals": {}, "counter": 0}
        return _notebook_sessions[tid]


def _reset_notebook():
    """Reset the notebook state for the current thread."""
    tid = threading.get_ident()
    with _notebook_lock:
        _notebook_sessions[tid] = {"globals": {}, "counter": 0}


@tool
def notebook_run(code: str = "") -> str:
    """
    Executes Python code in a stateful notebook environment.
    Variables, imports, and objects persist between calls within the same session.

    Use this for iterative data exploration, calculations, and analysis
    where you need to build on previous results.

    The environment is non-interactive: do NOT use input() or any blocking calls.

    IMPORTANT: Files are in the workspace directory. Use the pre-defined
    WORKSPACE_DIR variable to build file paths, e.g.:
        df = pd.read_csv(f"{WORKSPACE_DIR}/myfile.csv")

    Args:
        code: Python code to execute. Variables from previous cells are available.
    """
    if not code or not code.strip():
        return "Error: No code provided. Please pass Python code in the 'code' parameter."
    
    # Get per-thread session state
    session = _get_session()
    _notebook_globals = session["globals"]
    
    # Inject workspace path so code can find files
    from src.tools.workspace_context import tool_workspace_root
    _notebook_globals["WORKSPACE_DIR"] = tool_workspace_root()
    
    # Auto-fix common bare filename patterns: if code references a file without
    # WORKSPACE_DIR, prepend it. This handles the case where the LLM writes
    # pd.read_csv('file.csv') instead of pd.read_csv(f'{WORKSPACE_DIR}/file.csv')
    # Only match simple filenames (with extension, no path separators) to avoid
    # rewriting paths that are already absolute or use subdirectories intentionally.
    import re
    ws_dir = tool_workspace_root()
    # Fix read_csv, read_excel, open, etc. with bare filenames (no slashes)
    code = re.sub(
        r"""(read_csv|read_excel|read_json|read_parquet|read_table|open)\s*\(\s*(['"])(?!/|\.\./)([^'"\/]+\.[a-zA-Z0-9]+)\2""",
        lambda m: f'{m.group(1)}({m.group(2)}{ws_dir}/{m.group(3)}{m.group(2)}',
        code
    )
    
    session["counter"] += 1
    cell_num = session["counter"]

    stdout_buf = io.StringIO()
    stderr_buf = io.StringIO()

    try:
        with redirect_stdout(stdout_buf), redirect_stderr(stderr_buf):
            # Try exec first (statements), fall back to eval (expressions)
            try:
                compiled = compile(code, f"<cell_{cell_num}>", "exec")
                exec(compiled, _notebook_globals)
            except SyntaxError:
                # Maybe it's a single expression
                try:
                    result = eval(code, _notebook_globals)
                    if result is not None:
                        logger.debug("REPL result: %s", repr(result))
                except Exception:
                    raise

        out = stdout_buf.getvalue()
        err = stderr_buf.getvalue()

        parts = [f"[Cell {cell_num}]"]
        if out.strip():
            parts.append(out.strip())
        if err.strip():
            parts.append(f"stderr: {err.strip()}")
        if not out.strip() and not err.strip():
            parts.append("(executed successfully, no output)")

        result = "\n".join(parts)
        # Cap output
        if len(result) > 8000:
            result = result[:8000] + "\n... [output truncated]"
        return result

    except Exception:
        tb = traceback.format_exc()
        return f"[Cell {cell_num}] Error:\n{tb}"


@tool
def notebook_reset() -> str:
    """
    Resets the notebook environment, clearing all variables and imports.
    Use this to start fresh.
    """
    _reset_notebook()
    return "🔄 Notebook reset. All variables cleared."


@tool
def notebook_vars() -> str:
    """
    Lists all variables currently defined in the notebook environment.
    """
    session = _get_session()
    _notebook_globals = session["globals"]
    user_vars = {
        k: type(v).__name__
        for k, v in _notebook_globals.items()
        if not k.startswith("_") and k not in ("__builtins__",)
    }
    if not user_vars:
        return "📓 No variables defined in notebook."
    lines = ["📓 Notebook variables:"]
    for name, typ in sorted(user_vars.items()):
        lines.append(f"  • {name}: {typ}")
    return "\n".join(lines)
