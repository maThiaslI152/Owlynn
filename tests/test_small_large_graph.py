"""Graph compilation smoke test (legacy filename for small/large routing era)."""

import sys
from unittest.mock import MagicMock

sys.modules["mem0"] = MagicMock()

from langgraph.checkpoint.memory import MemorySaver

from src.agent.graph import build_graph


def test_graph_compile_with_checkpointer():
    assert build_graph().compile(checkpointer=MemorySaver()) is not None
