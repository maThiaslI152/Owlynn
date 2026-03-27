"""
Notebook Tool — Stateful Python REPL that persists variables across cells.
Mirrors Cowork's Notebook tool for iterative data exploration.

Unlike execute_python_code (fire-and-forget sandbox), this keeps state
in-process so variables, imports, and DataFrames survive between calls.
"""

import io
import sys
import traceback
from contextlib import redirect_stdout, redirect_stderr
from langchain_core.tools import tool

# Shared namespace across notebook cells within a session
_notebook_globals: dict = {}
_cell_counter: int = 0


def _reset_notebook():
    """Reset the notebook state."""
    global _notebook_globals, _cell_counter
    _notebook_globals = {}
    _cell_counter = 0


@tool
def notebook_run(code: str) -> str:
    """
    Executes Python code in a stateful notebook environment.
    Variables, imports, and objects persist between calls within the same session.

    Use this for iterative data exploration, calculations, and analysis
    where you need to build on previous results.

    The environment is non-interactive: do NOT use input() or any blocking calls.

    Args:
        code: Python code to execute. Variables from previous cells are available.
    """
    global _cell_counter
    _cell_counter += 1
    cell_num = _cell_counter

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
                        print(repr(result))
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
