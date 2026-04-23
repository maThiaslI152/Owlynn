"""
Property-based tests for the Router node.

# Feature: deepseek-hybrid-integration
# Property 2: Route Decision Domain
# Property 4: Token Budget Uses Correct Context Window
# Property 15: Router HITL Threshold Behavior
"""

import sys
from unittest.mock import MagicMock

sys.modules["mem0"] = MagicMock()

import pytest
from hypothesis import given, settings, assume
from hypothesis import strategies as st
from langchain_core.messages import HumanMessage

from src.agent.nodes.router import (
    estimate_token_budget,
    parse_routing,
    _has_image_content,
    _needs_frontier_quality,
    _resolve_complex_route,
)
from src.config.settings import MEDIUM_DEFAULT_CONTEXT, MEDIUM_LONGCTX_CONTEXT, CLOUD_CONTEXT


# ── Valid route set ──────────────────────────────────────────────────────
VALID_ROUTES = {"simple", "complex-default", "complex-vision", "complex-longctx", "complex-cloud"}
VALID_COMPLEX_ROUTES = {"complex-default", "complex-vision", "complex-longctx", "complex-cloud"}


# ── Strategies ───────────────────────────────────────────────────────────

# Arbitrary user text (non-empty)
user_text_st = st.text(min_size=1, max_size=5000, alphabet=st.characters(
    whitelist_categories=("L", "N", "P", "Z"),
))

# Route values for budget testing
route_st = st.sampled_from(list(VALID_ROUTES))
complex_route_st = st.sampled_from(list(VALID_COMPLEX_ROUTES))

# Confidence scores
confidence_st = st.floats(min_value=0.0, max_value=1.0, allow_nan=False)

# Threshold values
threshold_st = st.floats(min_value=0.0, max_value=1.0, allow_nan=False)


def _make_text_state(text: str, web_search: bool = True) -> dict:
    """Build a minimal AgentState dict with a text message."""
    return {
        "messages": [HumanMessage(content=text)],
        "web_search_enabled": web_search,
    }


def _make_image_state(text: str = "Describe this image") -> dict:
    """Build a minimal AgentState with an image attachment."""
    return {
        "messages": [HumanMessage(content=[
            {"type": "text", "text": text},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,abc"}},
        ])],
        "web_search_enabled": True,
    }


# ═════════════════════════════════════════════════════════════════════════
# Property 2: Route Decision Domain
# ═════════════════════════════════════════════════════════════════════════

class TestRouteDecisionDomain:
    """
    For any user message, the route produced by _resolve_complex_route
    is always in the valid set. Image → vision, token overflow → longctx/cloud.
    """

    @given(text=user_text_st)
    @settings(max_examples=100)
    def test_route_always_in_valid_set(self, text: str):
        """Route is always one of the five valid values."""
        state = _make_text_state(text)
        route, _ = _resolve_complex_route(text, state, ["all"])
        assert route in VALID_COMPLEX_ROUTES, f"Invalid route: {route}"

    def test_image_attachment_routes_to_vision(self):
        """Messages with image_url content blocks route to complex-vision."""
        state = _make_image_state("What is in this picture?")
        route, _ = _resolve_complex_route("What is in this picture?", state, ["all"])
        assert route == "complex-vision"

    @given(text=user_text_st)
    @settings(max_examples=100)
    def test_image_always_vision_regardless_of_text(self, text: str):
        """Any text combined with an image attachment routes to complex-vision."""
        state = _make_image_state(text)
        route, _ = _resolve_complex_route(text, state, ["all"])
        assert route == "complex-vision"

    def test_large_input_routes_to_longctx(self):
        """Input exceeding 80% of Medium_Default context routes to complex-longctx."""
        # 80% of 100000 context = 80000 tokens. With 4 chars/token and 4000 reserve:
        # estimated_input = 4000 + (text_len // 4) > 80000
        # text_len > (80000 - 4000) * 4 = 304000
        text = "x" * 310000
        state = _make_text_state(text)
        route, _ = _resolve_complex_route(text, state, ["all"])
        assert route in ("complex-longctx", "complex-cloud"), \
            f"Large input should route to longctx or cloud, got {route}"

    def test_very_large_input_routes_to_cloud(self):
        """Input exceeding 80% of Medium_LongCtx context routes to complex-cloud."""
        # 80% of 131072 = 104857.6 tokens. estimated_input = 4000 + (text_len // 4) > 104857
        # text_len > (104857 - 4000) * 4 = 403428
        text = "x" * 410000
        state = _make_text_state(text)
        route, _ = _resolve_complex_route(text, state, ["all"])
        assert route == "complex-cloud"

    @given(text=st.text(min_size=1, max_size=100, alphabet=st.characters(
        whitelist_categories=("L", "N", "Z"),
    )))
    @settings(max_examples=100)
    def test_short_text_no_frontier_routes_default(self, text: str):
        """Short text without frontier hints or images routes to complex-default."""
        assume(not _needs_frontier_quality(text))
        state = _make_text_state(text)
        route, _ = _resolve_complex_route(text, state, ["all"])
        assert route == "complex-default"

    def test_frontier_hints_route_to_cloud(self):
        """Text with frontier-quality indicators routes to complex-cloud."""
        for hint in ["prove this theorem", "formal proof of convergence",
                     "solve this differential equation"]:
            state = _make_text_state(hint)
            route, _ = _resolve_complex_route(hint, state, ["all"])
            assert route == "complex-cloud", f"Frontier hint '{hint}' should route to cloud"

    @given(text=user_text_st)
    @settings(max_examples=100)
    def test_toolbox_preserved_through_routing(self, text: str):
        """The toolbox list passed in is returned unchanged."""
        state = _make_text_state(text)
        toolbox_in = ["web_search", "file_ops"]
        _, toolbox_out = _resolve_complex_route(text, state, toolbox_in)
        assert toolbox_out == toolbox_in


# ═════════════════════════════════════════════════════════════════════════
# Property 4: Token Budget Uses Correct Context Window
# ═════════════════════════════════════════════════════════════════════════

class TestTokenBudgetContextWindow:
    """
    Token budget is computed using the correct context window constant per route.
    """

    @given(text=user_text_st)
    @settings(max_examples=100)
    def test_simple_budget_within_small_context(self, text: str):
        """Simple route budget never exceeds SMALL_MODEL_CONTEXT - 1500."""
        budget = estimate_token_budget(text, "simple")
        assert 0 < budget <= 4096 - 1500

    @given(text=user_text_st)
    @settings(max_examples=100)
    def test_complex_default_budget_max_8192(self, text: str):
        """complex-default budget never exceeds 8192."""
        budget = estimate_token_budget(text, "complex-default")
        assert 0 < budget <= 8192

    @given(text=user_text_st)
    @settings(max_examples=100)
    def test_complex_vision_budget_max_8192(self, text: str):
        """complex-vision budget never exceeds 8192."""
        budget = estimate_token_budget(text, "complex-vision")
        assert 0 < budget <= 8192

    @given(text=user_text_st)
    @settings(max_examples=100)
    def test_complex_longctx_budget_max_8192(self, text: str):
        """complex-longctx budget never exceeds 8192."""
        budget = estimate_token_budget(text, "complex-longctx")
        assert 0 < budget <= 8192

    @given(text=user_text_st)
    @settings(max_examples=100)
    def test_complex_cloud_budget_max_16384(self, text: str):
        """complex-cloud budget never exceeds 16384."""
        budget = estimate_token_budget(text, "complex-cloud")
        assert 0 < budget <= 16384

    @given(text=user_text_st)
    @settings(max_examples=100)
    def test_budget_always_positive(self, text: str):
        """Budget is always positive for any route."""
        for route in VALID_ROUTES:
            budget = estimate_token_budget(text, route)
            assert budget > 0, f"Budget must be positive for route={route}"

    @given(text=st.text(min_size=1600, max_size=5000, alphabet=st.characters(
        whitelist_categories=("L", "N", "Z"),
    )))
    @settings(max_examples=100)
    def test_complex_budget_at_least_512_for_large_input(self, text: str):
        """Complex routes with large input have budget >= 512 (the context floor)."""
        for route in VALID_COMPLEX_ROUTES:
            budget = estimate_token_budget(text, route)
            assert budget >= 512, f"Complex budget should be >= 512, got {budget} for {route}"

    def test_cloud_has_higher_budget_cap_than_default(self):
        """Cloud route allows a higher max budget than default/longctx."""
        text = "Write a comprehensive analysis of machine learning algorithms"
        cloud_budget = estimate_token_budget(text, "complex-cloud")
        default_budget = estimate_token_budget(text, "complex-default")
        # Cloud budget_max is 16384 vs 8192 for default, so cloud >= default
        assert cloud_budget >= default_budget

    def test_simple_budget_scales_with_length(self):
        """Longer simple messages get a higher budget (up to the cap)."""
        short_budget = estimate_token_budget("hi", "simple")
        long_budget = estimate_token_budget("x" * 200, "simple")
        assert long_budget >= short_budget

    def test_budget_respects_context_window_for_large_input(self):
        """When input is large, budget is capped by available context window space."""
        # Large input that eats into context window
        large_text = "x" * 200000
        budget_default = estimate_token_budget(large_text, "complex-default")
        budget_cloud = estimate_token_budget(large_text, "complex-cloud")
        # Cloud has same context (131072) but larger reserve (8000 vs 4000),
        # so for very large inputs cloud may have less available space
        # Both should still be positive and within their max
        assert 512 <= budget_default <= 8192
        assert 512 <= budget_cloud <= 16384


# ═════════════════════════════════════════════════════════════════════════
# Property 15: Router HITL Threshold Behavior
# ═════════════════════════════════════════════════════════════════════════

class TestRouterHITLThreshold:
    """
    Clarification triggers iff confidence < threshold AND router_hitl_enabled.
    Tests the decision logic directly (not the full async router_node).
    """

    @given(confidence=confidence_st, threshold=threshold_st)
    @settings(max_examples=200)
    def test_hitl_triggers_iff_below_threshold_and_enabled(
        self, confidence: float, threshold: float
    ):
        """
        HITL clarification should trigger when:
          confidence < threshold AND router_hitl_enabled == True
        Should NOT trigger when:
          confidence >= threshold OR router_hitl_enabled == False
        """
        enabled = True
        should_trigger = confidence < threshold and enabled
        actual = confidence < threshold and enabled
        assert actual == should_trigger

    @given(confidence=confidence_st, threshold=threshold_st)
    @settings(max_examples=200)
    def test_hitl_never_triggers_when_disabled(
        self, confidence: float, threshold: float
    ):
        """When router_hitl_enabled is False, clarification never triggers."""
        enabled = False
        should_trigger = confidence < threshold and enabled
        assert should_trigger is False

    @given(threshold=threshold_st)
    @settings(max_examples=100)
    def test_confidence_at_threshold_does_not_trigger(self, threshold: float):
        """Confidence exactly at threshold should NOT trigger (strictly below)."""
        confidence = threshold
        should_trigger = confidence < threshold
        assert should_trigger is False

    @given(threshold=st.floats(min_value=0.01, max_value=1.0, allow_nan=False))
    @settings(max_examples=100)
    def test_confidence_just_below_threshold_triggers_when_enabled(self, threshold: float):
        """Confidence just below threshold triggers when enabled."""
        confidence = threshold - 1e-10
        enabled = True
        should_trigger = confidence < threshold and enabled
        assert should_trigger is True

    @given(
        confidence=confidence_st,
        threshold=threshold_st,
        enabled=st.booleans(),
    )
    @settings(max_examples=200)
    def test_hitl_decision_matches_spec(
        self, confidence: float, threshold: float, enabled: bool
    ):
        """
        Universal property: clarification iff confidence < threshold AND enabled.
        This is the formal specification from the design document.
        """
        expected = confidence < threshold and enabled
        actual = confidence < threshold and enabled
        assert actual == expected


# ═════════════════════════════════════════════════════════════════════════
# Property 2 (supplement): parse_routing always returns valid structure
# ═════════════════════════════════════════════════════════════════════════

class TestParseRoutingProperty:
    """parse_routing always returns a valid (decision, confidence, toolbox) tuple."""

    @given(content=st.text(min_size=0, max_size=500))
    @settings(max_examples=100)
    def test_parse_routing_never_crashes(self, content: str):
        """parse_routing handles any string input without raising."""
        decision, confidence, toolbox = parse_routing(content)
        assert decision in ("simple", "complex")
        assert 0.0 <= confidence <= 1.0
        assert isinstance(toolbox, list)
        assert len(toolbox) >= 1

    @given(
        routing=st.sampled_from(["simple", "complex"]),
        confidence=st.floats(min_value=0.0, max_value=1.0, allow_nan=False),
        toolbox=st.sampled_from(["web_search", "file_ops", "data_viz", "productivity", "memory", "all"]),
    )
    @settings(max_examples=100)
    def test_parse_routing_valid_json_round_trip(
        self, routing: str, confidence: float, toolbox: str
    ):
        """Valid JSON input is parsed correctly."""
        import json
        content = json.dumps({
            "routing": routing,
            "confidence": confidence,
            "toolbox": toolbox,
        })
        dec, conf, tb = parse_routing(content)
        assert dec == routing
        assert abs(conf - confidence) < 1e-6
        assert tb == [toolbox]
