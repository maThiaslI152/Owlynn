"""
Property-based tests for the Complex Node behavior.

# Feature: deepseek-hybrid-integration
# Property 7: Model Provenance Matches Route
# Property 8: Cloud-Only Anonymization
"""

import sys
from unittest.mock import MagicMock

sys.modules["mem0"] = MagicMock()

import asyncio
import pytest
from unittest.mock import AsyncMock, patch
from hypothesis import given, settings, assume
from hypothesis import strategies as st
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from src.agent.state import AgentState


# ── Valid domains ────────────────────────────────────────────────────────

VALID_ROUTES = {"simple", "complex-default", "complex-vision", "complex-longctx", "complex-cloud"}
COMPLEX_ROUTES = {"complex-default", "complex-vision", "complex-longctx", "complex-cloud"}

ROUTE_TO_MODEL = {
    "complex-default": "medium-default",
    "complex-vision": "medium-vision",
    "complex-longctx": "medium-longctx",
    "complex-cloud": "large-cloud",
}

LOCAL_ROUTES = {"complex-default", "complex-vision", "complex-longctx"}


# ── Strategies ───────────────────────────────────────────────────────────

route_st = st.sampled_from(sorted(COMPLEX_ROUTES))
local_route_st = st.sampled_from(sorted(LOCAL_ROUTES))
bool_st = st.booleans()
user_text_st = st.text(min_size=1, max_size=200, alphabet=st.characters(
    whitelist_categories=("L", "N", "P", "Z"),
))


# ── Helpers ──────────────────────────────────────────────────────────────

def _make_state(route: str, text: str = "Hello", anon_enabled: bool = True) -> dict:
    """Build a minimal AgentState dict for complex_llm_node."""
    return {
        "messages": [HumanMessage(content=text)],
        "route": route,
        "mode": "tools_on",
        "web_search_enabled": True,
        "memory_context": "None",
        "persona": "Test persona",
        "response_style": None,
        "security_decision": None,
        "security_reason": None,
        "token_budget": 4096,
        "selected_toolboxes": ["all"],
    }


def _mock_profile(anon_enabled: bool = True) -> dict:
    """Return a profile dict with configurable anonymization toggle."""
    return {
        "name": "TestUser",
        "small_llm_base_url": "http://127.0.0.1:1234/v1",
        "cloud_llm_base_url": "https://api.deepseek.com/v1",
        "cloud_anonymization_enabled": anon_enabled,
        "custom_sensitive_terms": [],
        "lm_studio_fold_system": True,
        "medium_models": {
            "default": "qwen/qwen3.5-9b",
            "vision": "zai-org/glm-4.6v-flash",
            "longctx": "LFM2 8B A1B GGUF Q8_0",
        },
    }


def _make_mock_llm():
    """Create a mock LLM that returns a simple AIMessage."""
    mock_llm = MagicMock()
    mock_response = AIMessage(content="Test response")
    mock_bound = MagicMock()
    mock_bound.ainvoke = AsyncMock(return_value=mock_response)
    mock_bound.bind = MagicMock(return_value=mock_bound)
    mock_llm.bind_tools = MagicMock(return_value=mock_bound)
    mock_llm.bind = MagicMock(return_value=mock_bound)
    return mock_llm


# ═════════════════════════════════════════════════════════════════════════
# Property 7: Model Provenance Matches Route
# ═════════════════════════════════════════════════════════════════════════


class TestModelProvenanceMatchesRoute:
    """
    For any route value processed by the Complex_Node, the model_used field
    in the returned AgentState SHALL correspond to the route.
    """

    @given(route=route_st, text=user_text_st)
    @settings(max_examples=100, deadline=10000)
    @pytest.mark.asyncio
    async def test_model_used_matches_route_for_all_complex_routes(self, route: str, text: str):
        """model_used always corresponds to the route when no errors occur."""
        state = _make_state(route, text)
        mock_llm = _make_mock_llm()
        profile = _mock_profile()

        with patch("src.agent.nodes.complex.get_medium_llm", new_callable=AsyncMock, return_value=mock_llm), \
             patch("src.agent.nodes.complex.get_cloud_llm", new_callable=AsyncMock, return_value=mock_llm), \
             patch("src.agent.nodes.complex.get_profile", return_value=profile):
            from src.agent.nodes.complex import complex_llm_node
            result = await complex_llm_node(state)

        expected_label = ROUTE_TO_MODEL[route]
        assert result["model_used"] == expected_label, (
            f"Route {route!r} should produce model_used={expected_label!r}, "
            f"got {result['model_used']!r}"
        )

    @given(route=local_route_st, text=user_text_st)
    @settings(max_examples=100, deadline=10000)
    @pytest.mark.asyncio
    async def test_local_routes_never_produce_cloud_label(self, route: str, text: str):
        """Local routes must never set model_used to large-cloud."""
        state = _make_state(route, text)
        mock_llm = _make_mock_llm()
        profile = _mock_profile()

        with patch("src.agent.nodes.complex.get_medium_llm", new_callable=AsyncMock, return_value=mock_llm), \
             patch("src.agent.nodes.complex.get_cloud_llm", new_callable=AsyncMock, return_value=mock_llm), \
             patch("src.agent.nodes.complex.get_profile", return_value=profile):
            from src.agent.nodes.complex import complex_llm_node
            result = await complex_llm_node(state)

        assert "cloud" not in result["model_used"], (
            f"Local route {route!r} should not produce cloud model_used, "
            f"got {result['model_used']!r}"
        )

    @pytest.mark.asyncio
    async def test_cloud_route_produces_large_cloud(self):
        """complex-cloud route must set model_used to large-cloud."""
        state = _make_state("complex-cloud")
        mock_llm = _make_mock_llm()
        profile = _mock_profile()

        with patch("src.agent.nodes.complex.get_medium_llm", new_callable=AsyncMock, return_value=mock_llm), \
             patch("src.agent.nodes.complex.get_cloud_llm", new_callable=AsyncMock, return_value=mock_llm), \
             patch("src.agent.nodes.complex.get_profile", return_value=profile):
            from src.agent.nodes.complex import complex_llm_node
            result = await complex_llm_node(state)

        assert result["model_used"] == "large-cloud"

    @pytest.mark.asyncio
    async def test_default_route_produces_medium_default(self):
        """complex-default route must set model_used to medium-default."""
        state = _make_state("complex-default")
        mock_llm = _make_mock_llm()
        profile = _mock_profile()

        with patch("src.agent.nodes.complex.get_medium_llm", new_callable=AsyncMock, return_value=mock_llm), \
             patch("src.agent.nodes.complex.get_cloud_llm", new_callable=AsyncMock, return_value=mock_llm), \
             patch("src.agent.nodes.complex.get_profile", return_value=profile):
            from src.agent.nodes.complex import complex_llm_node
            result = await complex_llm_node(state)

        assert result["model_used"] == "medium-default"

    @pytest.mark.asyncio
    async def test_vision_route_produces_medium_vision(self):
        """complex-vision route must set model_used to medium-vision."""
        state = _make_state("complex-vision")
        mock_llm = _make_mock_llm()
        profile = _mock_profile()

        with patch("src.agent.nodes.complex.get_medium_llm", new_callable=AsyncMock, return_value=mock_llm), \
             patch("src.agent.nodes.complex.get_cloud_llm", new_callable=AsyncMock, return_value=mock_llm), \
             patch("src.agent.nodes.complex.get_profile", return_value=profile):
            from src.agent.nodes.complex import complex_llm_node
            result = await complex_llm_node(state)

        assert result["model_used"] == "medium-vision"

    @pytest.mark.asyncio
    async def test_longctx_route_produces_medium_longctx(self):
        """complex-longctx route must set model_used to medium-longctx."""
        state = _make_state("complex-longctx")
        mock_llm = _make_mock_llm()
        profile = _mock_profile()

        with patch("src.agent.nodes.complex.get_medium_llm", new_callable=AsyncMock, return_value=mock_llm), \
             patch("src.agent.nodes.complex.get_cloud_llm", new_callable=AsyncMock, return_value=mock_llm), \
             patch("src.agent.nodes.complex.get_profile", return_value=profile):
            from src.agent.nodes.complex import complex_llm_node
            result = await complex_llm_node(state)

        assert result["model_used"] == "medium-longctx"


    @given(route=route_st)
    @settings(max_examples=100, deadline=10000)
    @pytest.mark.asyncio
    async def test_fallback_label_has_suffix_on_swap_error(self, route: str):
        """When ModelSwapError occurs, model_used must contain '-fallback' suffix."""
        from src.agent.swap_manager import ModelSwapError

        state = _make_state(route)
        mock_llm = _make_mock_llm()
        profile = _mock_profile()

        # First call raises, second (fallback) succeeds
        async def _medium_side_effect(variant="default"):
            if variant != "default":
                raise ModelSwapError(f"Cannot swap to {variant}")
            return mock_llm

        async def _cloud_side_effect():
            from src.agent.llm import CloudUnavailableError
            raise CloudUnavailableError("No key")

        with patch("src.agent.nodes.complex.get_medium_llm", side_effect=_medium_side_effect), \
             patch("src.agent.nodes.complex.get_cloud_llm", side_effect=_cloud_side_effect), \
             patch("src.agent.nodes.complex.get_profile", return_value=profile):
            from src.agent.nodes.complex import complex_llm_node

            if route == "complex-default":
                # Default doesn't swap, so no error path — just verify normal label
                result = await complex_llm_node(state)
                assert result["model_used"] == "medium-default"
            else:
                # Non-default routes should fall back
                result = await complex_llm_node(state)
                assert "fallback" in result["model_used"], (
                    f"Route {route!r} with swap error should produce fallback label, "
                    f"got {result['model_used']!r}"
                )

    @given(route=route_st)
    @settings(max_examples=100, deadline=10000)
    @pytest.mark.asyncio
    async def test_model_used_always_a_string(self, route: str):
        """model_used must always be a non-empty string."""
        state = _make_state(route)
        mock_llm = _make_mock_llm()
        profile = _mock_profile()

        with patch("src.agent.nodes.complex.get_medium_llm", new_callable=AsyncMock, return_value=mock_llm), \
             patch("src.agent.nodes.complex.get_cloud_llm", new_callable=AsyncMock, return_value=mock_llm), \
             patch("src.agent.nodes.complex.get_profile", return_value=profile):
            from src.agent.nodes.complex import complex_llm_node
            result = await complex_llm_node(state)

        assert isinstance(result["model_used"], str)
        assert len(result["model_used"]) > 0


# ═════════════════════════════════════════════════════════════════════════
# Property 8: Cloud-Only Anonymization
# ═════════════════════════════════════════════════════════════════════════


class TestCloudOnlyAnonymization:
    """
    For any route value and any cloud_anonymization_enabled setting, the
    Complex_Node SHALL invoke the Anonymization_Engine if and only if the
    route is "complex-cloud" AND cloud_anonymization_enabled is True.
    """

    @given(route=local_route_st, anon_enabled=bool_st, text=user_text_st)
    @settings(max_examples=100, deadline=10000)
    @pytest.mark.asyncio
    async def test_local_routes_never_anonymize(self, route: str, anon_enabled: bool, text: str):
        """Local routes must never call anonymize, regardless of toggle."""
        state = _make_state(route, text)
        mock_llm = _make_mock_llm()
        profile = _mock_profile(anon_enabled)

        with patch("src.agent.nodes.complex.get_medium_llm", new_callable=AsyncMock, return_value=mock_llm), \
             patch("src.agent.nodes.complex.get_cloud_llm", new_callable=AsyncMock, return_value=mock_llm), \
             patch("src.agent.nodes.complex.get_profile", return_value=profile), \
             patch("src.agent.nodes.complex.anonymize", wraps=None) as mock_anon:
            # Use a side_effect that tracks calls but returns passthrough
            mock_anon.side_effect = lambda text, ctx=None: (text, {})
            from src.agent.nodes.complex import complex_llm_node
            result = await complex_llm_node(state)

        mock_anon.assert_not_called(), (
            f"Local route {route!r} with anon_enabled={anon_enabled} "
            f"should not invoke anonymize"
        )

    @given(text=user_text_st)
    @settings(max_examples=100, deadline=10000)
    @pytest.mark.asyncio
    async def test_cloud_route_with_anon_enabled_calls_anonymize(self, text: str):
        """Cloud route with anonymization enabled must call anonymize."""
        state = _make_state("complex-cloud", text)
        mock_llm = _make_mock_llm()
        profile = _mock_profile(anon_enabled=True)

        with patch("src.agent.nodes.complex.get_medium_llm", new_callable=AsyncMock, return_value=mock_llm), \
             patch("src.agent.nodes.complex.get_cloud_llm", new_callable=AsyncMock, return_value=mock_llm), \
             patch("src.agent.nodes.complex.get_profile", return_value=profile), \
             patch("src.agent.nodes.complex.anonymize") as mock_anon:
            mock_anon.return_value = (text, {})
            from src.agent.nodes.complex import complex_llm_node
            result = await complex_llm_node(state)

        assert mock_anon.call_count > 0, (
            "Cloud route with anonymization enabled must call anonymize"
        )

    @given(text=user_text_st)
    @settings(max_examples=100, deadline=10000)
    @pytest.mark.asyncio
    async def test_cloud_route_with_anon_disabled_skips_anonymize(self, text: str):
        """Cloud route with anonymization disabled must not call anonymize."""
        state = _make_state("complex-cloud", text)
        mock_llm = _make_mock_llm()
        profile = _mock_profile(anon_enabled=False)

        with patch("src.agent.nodes.complex.get_medium_llm", new_callable=AsyncMock, return_value=mock_llm), \
             patch("src.agent.nodes.complex.get_cloud_llm", new_callable=AsyncMock, return_value=mock_llm), \
             patch("src.agent.nodes.complex.get_profile", return_value=profile), \
             patch("src.agent.nodes.complex.anonymize") as mock_anon:
            mock_anon.return_value = (text, {})
            from src.agent.nodes.complex import complex_llm_node
            result = await complex_llm_node(state)

        mock_anon.assert_not_called(), (
            "Cloud route with anonymization disabled must not call anonymize"
        )

    @given(
        route=route_st,
        anon_enabled=bool_st,
    )
    @settings(max_examples=100, deadline=10000)
    @pytest.mark.asyncio
    async def test_anonymize_iff_cloud_and_enabled(self, route: str, anon_enabled: bool):
        """Anonymize is called iff route is complex-cloud AND anon_enabled is True."""
        state = _make_state(route, "Test message with [email]")
        mock_llm = _make_mock_llm()
        profile = _mock_profile(anon_enabled)

        with patch("src.agent.nodes.complex.get_medium_llm", new_callable=AsyncMock, return_value=mock_llm), \
             patch("src.agent.nodes.complex.get_cloud_llm", new_callable=AsyncMock, return_value=mock_llm), \
             patch("src.agent.nodes.complex.get_profile", return_value=profile), \
             patch("src.agent.nodes.complex.anonymize") as mock_anon:
            mock_anon.return_value = ("anonymized", {"[EMAIL_1]": "[email]"})
            from src.agent.nodes.complex import complex_llm_node
            result = await complex_llm_node(state)

        should_anonymize = (route == "complex-cloud" and anon_enabled)
        was_called = mock_anon.call_count > 0

        assert was_called == should_anonymize, (
            f"route={route!r}, anon_enabled={anon_enabled}: "
            f"expected anonymize called={should_anonymize}, actual={was_called}"
        )

    @pytest.mark.asyncio
    async def test_cloud_fallback_skips_deanonymize(self):
        """When cloud falls back to local, deanonymize must be skipped."""
        from src.agent.llm import CloudUnavailableError

        state = _make_state("complex-cloud", "Hello TestUser, my email is [email]")
        mock_llm = _make_mock_llm()
        profile = _mock_profile(anon_enabled=True)

        # Cloud LLM raises CloudUnavailableError, triggering fallback to medium-default
        async def _cloud_raises():
            raise CloudUnavailableError("No API key configured")

        with patch("src.agent.nodes.complex.get_medium_llm", new_callable=AsyncMock, return_value=mock_llm), \
             patch("src.agent.nodes.complex.get_cloud_llm", side_effect=_cloud_raises), \
             patch("src.agent.nodes.complex.get_profile", return_value=profile), \
             patch("src.agent.nodes.complex.deanonymize") as mock_deanon:
            from src.agent.nodes.complex import complex_llm_node
            result = await complex_llm_node(state)

        # Fallback occurred — deanonymize should not be called
        mock_deanon.assert_not_called()
        assert "fallback" in result["model_used"]
