"""Smoke tests for LangGraph wiring (post security-proxy refactor)."""

import sys
from unittest.mock import MagicMock

sys.modules["mem0"] = MagicMock()

import pytest
from langgraph.checkpoint.memory import MemorySaver

from src.agent.graph import build_graph, route_decision


def test_build_graph_compiles_with_memory_saver():
    compiled = build_graph().compile(checkpointer=MemorySaver())
    assert compiled is not None


# ── route_decision mapping tests ────────────────────────────────────────

class TestRouteDecision:
    """Verify route_decision maps all 5 routes correctly."""

    def test_simple_route(self):
        state = {"route": "simple"}
        assert route_decision(state) == "simple"

    def test_complex_default_route(self):
        state = {"route": "complex-default"}
        assert route_decision(state) == "complex"

    def test_complex_vision_route(self):
        state = {"route": "complex-vision"}
        assert route_decision(state) == "complex"

    def test_complex_longctx_route(self):
        state = {"route": "complex-longctx"}
        assert route_decision(state) == "complex"

    def test_complex_cloud_route(self):
        state = {"route": "complex-cloud"}
        assert route_decision(state) == "complex"

    def test_unrecognized_route_defaults_to_complex(self):
        state = {"route": "unknown-route"}
        assert route_decision(state) == "complex"

    def test_missing_route_defaults_to_complex(self):
        state = {}
        assert route_decision(state) == "complex"

    def test_none_route_defaults_to_complex(self):
        state = {"route": None}
        assert route_decision(state) == "complex"
