"""Unit tests for workspace upload path parsing (auto-read fallback)."""

import sys
from unittest.mock import MagicMock

sys.modules["mem0"] = MagicMock()

from src.agent.nodes.complex import (  # noqa: E402
    _latest_user_text,
    _looks_like_prose_tool_stall,
    _user_intent_needs_workspace_read,
    _workspace_paths_from_text,
)
from langchain_core.messages import AIMessage, HumanMessage  # noqa: E402


def test_workspace_paths_backtick_injection():
    t = "[Workspace file `chapter.pdf` — text extracted …]\n\n---\nhi\n---"
    assert _workspace_paths_from_text(t) == ["chapter.pdf"]


def test_workspace_paths_legacy_bracket():
    t = "[File: notes.pdf uploaded to workspace. Use tool.]\n\nGo."
    assert "notes.pdf" in _workspace_paths_from_text(t)


def test_latest_user_text_multimodal():
    messages = [
        HumanMessage(content="old"),
        HumanMessage(content=[{"type": "text", "text": "new with `f.pdf`"}]),
    ]
    assert "new" in _latest_user_text(messages)


def test_user_intent_study():
    assert _user_intent_needs_workspace_read("Can you help me study this slide")


def test_prose_tool_stall_detects_read_workspace():
    m = AIMessage(content="Use read_workspace_file to open x.pdf.")
    assert _looks_like_prose_tool_stall(m) is True


def test_prose_tool_stall_respects_substantive_answer():
    m = AIMessage(content="Here is a long " + ("paragraph " * 80) + " with no tool names.")
    assert _looks_like_prose_tool_stall(m) is False
