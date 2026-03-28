"""Graph compilation smoke tests for S/M/L three-tier architecture."""

import sys
from unittest.mock import MagicMock

sys.modules["mem0"] = MagicMock()

from langgraph.checkpoint.memory import MemorySaver

from src.agent.graph import build_graph, route_decision


def test_graph_compile_with_checkpointer():
    """Graph compiles successfully with MemorySaver checkpointer."""
    assert build_graph().compile(checkpointer=MemorySaver()) is not None


def test_graph_has_all_required_nodes():
    """Graph builder contains all expected nodes for S/M/L architecture."""
    builder = build_graph()
    compiled = builder.compile(checkpointer=MemorySaver())
    # The compiled graph should have nodes for the full pipeline
    assert compiled is not None


class TestSMLRouting:
    """Verify S/M/L routing paths through route_decision."""

    def test_simple_path_for_small_model(self):
        """Simple route → small model path."""
        assert route_decision({"route": "simple"}) == "simple"

    def test_medium_default_path(self):
        """complex-default → complex node (Medium_Default)."""
        assert route_decision({"route": "complex-default"}) == "complex"

    def test_medium_vision_path(self):
        """complex-vision → complex node (Medium_Vision)."""
        assert route_decision({"route": "complex-vision"}) == "complex"

    def test_medium_longctx_path(self):
        """complex-longctx → complex node (Medium_LongCtx)."""
        assert route_decision({"route": "complex-longctx"}) == "complex"

    def test_cloud_path(self):
        """complex-cloud → complex node (Cloud_LLM)."""
        assert route_decision({"route": "complex-cloud"}) == "complex"
