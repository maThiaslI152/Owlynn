"""Smoke tests for LangGraph wiring (post security-proxy refactor)."""

import sys
from unittest.mock import MagicMock

sys.modules["mem0"] = MagicMock()

import pytest
from langgraph.checkpoint.memory import MemorySaver

from src.agent.graph import build_graph


def test_build_graph_compiles_with_memory_saver():
    compiled = build_graph().compile(checkpointer=MemorySaver())
    assert compiled is not None
