"""
Todo/Task Tracking — Persistent task list the agent can manage.
Mirrors Cowork's Todo tool for tracking work items across sessions.
"""

import json
import time
from pathlib import Path
from langchain_core.tools import tool
from src.config.settings import DATA_DIR

_TODO_PATH = DATA_DIR / "todos.json"


def _load_todos() -> list[dict]:
    try:
        return json.loads(_TODO_PATH.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def _save_todos(todos: list[dict]):
    _TODO_PATH.parent.mkdir(parents=True, exist_ok=True)
    _TODO_PATH.write_text(json.dumps(todos, ensure_ascii=False, indent=2), encoding="utf-8")


def _next_id(todos: list[dict]) -> int:
    return max((t.get("id", 0) for t in todos), default=0) + 1


@tool
def todo_add(task: str, priority: str = "medium") -> str:
    """
    Adds a new task to the todo list.

    Args:
        task: Description of the task.
        priority: Priority level — low, medium, or high.
    """
    todos = _load_todos()
    item = {
        "id": _next_id(todos),
        "task": task.strip(),
        "priority": priority.strip().lower(),
        "status": "pending",
        "created_at": time.strftime("%Y-%m-%d %H:%M"),
        "completed_at": None,
    }
    todos.append(item)
    _save_todos(todos)
    return f"✅ Added task #{item['id']}: {task}"


@tool
def todo_list(status: str = "all") -> str:
    """
    Lists tasks from the todo list.

    Args:
        status: Filter by status — all, pending, done.
    """
    todos = _load_todos()
    if not todos:
        return "📋 Todo list is empty."

    if status != "all":
        todos = [t for t in todos if t["status"] == status]

    if not todos:
        return f"📋 No tasks with status '{status}'."

    lines = ["📋 Todo List:"]
    for t in todos:
        icon = "✅" if t["status"] == "done" else "⬜"
        pri = {"high": "🔴", "medium": "🟡", "low": "🟢"}.get(t["priority"], "⚪")
        lines.append(f"  {icon} #{t['id']} [{pri}] {t['task']}")
    return "\n".join(lines)


@tool
def todo_complete(task_id: int) -> str:
    """
    Marks a task as completed.

    Args:
        task_id: The ID number of the task to complete.
    """
    todos = _load_todos()
    for t in todos:
        if t["id"] == task_id:
            t["status"] = "done"
            t["completed_at"] = time.strftime("%Y-%m-%d %H:%M")
            _save_todos(todos)
            return f"✅ Task #{task_id} marked as done."
    return f"Task #{task_id} not found."


@tool
def todo_remove(task_id: int) -> str:
    """
    Removes a task from the todo list.

    Args:
        task_id: The ID number of the task to remove.
    """
    todos = _load_todos()
    before = len(todos)
    todos = [t for t in todos if t["id"] != task_id]
    if len(todos) < before:
        _save_todos(todos)
        return f"🗑️ Task #{task_id} removed."
    return f"Task #{task_id} not found."
