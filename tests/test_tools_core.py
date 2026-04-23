"""Tests for core workspace tools (no sandbox dependency)."""
import sys
import os
import tempfile
from unittest.mock import MagicMock, patch

sys.modules["mem0"] = MagicMock()

import pytest
from src.tools.core_tools import (
    read_workspace_file,
    write_workspace_file,
    edit_workspace_file,
    list_workspace_files,
    delete_workspace_file,
    recall_memories,
    get_safe_workspace_path,
)


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    """Create a temp workspace and patch the workspace root."""
    monkeypatch.setattr("src.tools.core_tools.BASE_WORKSPACE_DIR", str(tmp_path))
    monkeypatch.setattr("src.tools.core_tools.tool_workspace_root", lambda: str(tmp_path))
    return tmp_path


def test_write_and_read(workspace):
    result = write_workspace_file.invoke({"filename": "test.txt", "content": "hello world"})
    assert "Written" in result
    assert (workspace / "test.txt").exists()

    content = read_workspace_file.invoke({"filename": "test.txt"})
    assert content == "hello world"


def test_edit_file(workspace):
    (workspace / "doc.txt").write_text("foo bar baz")
    result = edit_workspace_file.invoke({
        "filename": "doc.txt",
        "search_pattern": "bar",
        "replacement_text": "qux",
    })
    assert "Updated" in result
    assert (workspace / "doc.txt").read_text() == "foo qux baz"


def test_edit_pattern_not_found(workspace):
    (workspace / "doc.txt").write_text("hello")
    result = edit_workspace_file.invoke({
        "filename": "doc.txt",
        "search_pattern": "missing",
        "replacement_text": "x",
    })
    assert "not found" in result.lower() or "Pattern" in result


def test_list_files(workspace):
    (workspace / "a.txt").write_text("a")
    (workspace / "b.txt").write_text("bb")
    (workspace / "subdir").mkdir()
    result = list_workspace_files.invoke({"directory": "."})
    assert "a.txt" in result
    assert "b.txt" in result
    assert "subdir" in result


def test_delete_file(workspace):
    (workspace / "del.txt").write_text("delete me")
    result = delete_workspace_file.invoke({"filename": "del.txt"})
    assert "Deleted" in result
    assert not (workspace / "del.txt").exists()


def test_delete_nonexistent(workspace):
    result = delete_workspace_file.invoke({"filename": "nope.txt"})
    assert "not found" in result.lower()


def test_read_nonexistent(workspace):
    result = read_workspace_file.invoke({"filename": "nope.txt"})
    assert "not found" in result.lower() or "Error" in result


def test_path_traversal_blocked(workspace):
    _, err = get_safe_workspace_path("../../etc/passwd")
    assert err is not None
    assert "denied" in err.lower() or "outside" in err.lower()


def test_recall_memories_empty():
    with patch("src.tools.core_tools.search_memories", return_value=[]):
        result = recall_memories.invoke({"query": "test"})
        assert "No relevant" in result


def test_recall_memories_with_results():
    fake = [{"fact": "User likes Python", "timestamp": "2026-01-01T00:00:00"}]
    with patch("src.tools.core_tools.search_memories", return_value=fake):
        result = recall_memories.invoke({"query": "python"})
        assert "Python" in result
