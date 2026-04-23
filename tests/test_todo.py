"""Tests for the todo tool."""
import sys
import json
from unittest.mock import MagicMock
sys.modules["mem0"] = MagicMock()

import pytest
from src.tools.todo import todo_add, todo_list, todo_complete, todo_remove, _TODO_PATH


@pytest.fixture(autouse=True)
def clean_todos(tmp_path, monkeypatch):
    """Use a temp file for todos."""
    todo_file = tmp_path / "todos.json"
    monkeypatch.setattr("src.tools.todo._TODO_PATH", todo_file)
    yield todo_file


def test_add_and_list():
    result = todo_add.invoke({"task": "Buy milk", "priority": "low"})
    assert "Added" in result
    assert "#1" in result

    result = todo_list.invoke({"status": "all"})
    assert "Buy milk" in result
    assert "🟢" in result  # low priority


def test_add_multiple():
    todo_add.invoke({"task": "Task A"})
    todo_add.invoke({"task": "Task B", "priority": "high"})
    result = todo_list.invoke({"status": "all"})
    assert "Task A" in result
    assert "Task B" in result
    assert "🔴" in result  # high priority


def test_complete():
    todo_add.invoke({"task": "Finish report"})
    result = todo_complete.invoke({"task_id": 1})
    assert "done" in result.lower()

    result = todo_list.invoke({"status": "done"})
    assert "Finish report" in result
    assert "✅" in result


def test_complete_nonexistent():
    result = todo_complete.invoke({"task_id": 999})
    assert "not found" in result.lower()


def test_list_empty():
    result = todo_list.invoke({"status": "all"})
    assert "empty" in result.lower()


def test_list_filter_pending():
    todo_add.invoke({"task": "Pending task"})
    todo_add.invoke({"task": "Done task"})
    todo_complete.invoke({"task_id": 2})

    pending = todo_list.invoke({"status": "pending"})
    assert "Pending task" in pending
    assert "Done task" not in pending
