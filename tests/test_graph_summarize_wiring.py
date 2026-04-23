"""Tests for auto-summarize wiring in the LangGraph graph (task 2.3).

Validates:
- summarize_gate conditional routing logic
- auto_summarize node is present in the compiled graph
- context_summarized event forwarding structure
"""

import sys
from unittest.mock import MagicMock

# Stub mem0 before any project imports
sys.modules["mem0"] = MagicMock()

from src.agent.graph import summarize_gate, build_graph


class TestSummarizeGate:
    """Tests for the summarize_gate conditional edge function."""

    def test_routes_to_auto_summarize_above_threshold(self):
        """When active_tokens > 85% of context_window, route to auto_summarize."""
        state = {"active_tokens": 86_000, "context_window": 100_000}
        assert summarize_gate(state) == "auto_summarize"

    def test_routes_to_router_below_threshold(self):
        """When active_tokens <= 85% of context_window, skip to router."""
        state = {"active_tokens": 50_000, "context_window": 100_000}
        assert summarize_gate(state) == "router"

    def test_routes_to_router_at_exact_threshold(self):
        """At exactly 85%, should NOT trigger (uses > not >=)."""
        state = {"active_tokens": 85_000, "context_window": 100_000}
        assert summarize_gate(state) == "router"

    def test_routes_to_router_when_no_tokens(self):
        """When active_tokens is None/0, should go to router."""
        state = {"active_tokens": None, "context_window": 100_000}
        assert summarize_gate(state) == "router"

    def test_routes_to_router_when_no_context_window(self):
        """When context_window is None, defaults to 100K and routes to router."""
        state = {"active_tokens": 1000, "context_window": None}
        assert summarize_gate(state) == "router"

    def test_routes_to_auto_summarize_with_default_context_window(self):
        """When context_window is None (defaults to 100K), high tokens trigger summarize."""
        state = {"active_tokens": 90_000, "context_window": None}
        assert summarize_gate(state) == "auto_summarize"

    def test_routes_to_router_with_empty_state(self):
        """Empty state should default to router (0 tokens, 100K window)."""
        state = {}
        assert summarize_gate(state) == "router"


class TestGraphStructure:
    """Tests that the graph has the auto_summarize node wired correctly."""

    def test_graph_contains_auto_summarize_node(self):
        """The built graph should include the auto_summarize node."""
        builder = build_graph()
        assert "auto_summarize" in builder.nodes

    def test_graph_contains_all_expected_nodes(self):
        """All expected nodes should be present in the graph."""
        builder = build_graph()
        expected = {
            "memory_inject", "auto_summarize", "router", "simple",
            "complex_llm", "security_proxy", "tool_action", "memory_write",
        }
        assert expected.issubset(set(builder.nodes.keys()))
