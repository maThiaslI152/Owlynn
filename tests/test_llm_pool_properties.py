"""
Property-based tests for the LLMPool.

# Feature: deepseek-hybrid-integration, Property 3: LLMPool Variant Tracking
# Validates: Requirements 2.2, 2.4, 2.5, 2.9

# Feature: deepseek-hybrid-integration, Property 10: API Key Resolution Order
# Validates: Requirements 1.1, 1.2
"""

import sys
from contextlib import contextmanager
from unittest.mock import AsyncMock, MagicMock, patch

sys.modules["mem0"] = MagicMock()

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from src.agent.llm import CloudUnavailableError, LLMPool

# ── Test profile ─────────────────────────────────────────────────────────

PROFILE = {
    "small_llm_base_url": "http://127.0.0.1:1234/v1",
    "small_llm_model_name": "liquid/lfm2.5-1.2b",
    "llm_base_url": "http://127.0.0.1:1234/v1",
    "medium_models": {
        "default": "qwen/qwen3.5-9b",
        "vision": "zai-org/glm-4.6v-flash",
        "longctx": "LFM2 8B A1B GGUF Q8_0",
    },
    "cloud_llm_base_url": "https://api.deepseek.com/v1",
    "cloud_llm_model_name": "deepseek-chat",
    "deepseek_api_key": "",
}

# ── Helpers ──────────────────────────────────────────────────────────────


@contextmanager
def fresh_pool():
    """Reset LLMPool state for each hypothesis example."""
    LLMPool.clear()
    LLMPool._swap_manager = None
    try:
        yield
    finally:
        LLMPool.clear()
        LLMPool._swap_manager = None


# ── Strategies ───────────────────────────────────────────────────────────

VALID_VARIANTS = ["default", "vision", "longctx"]

variant_st = st.sampled_from(VALID_VARIANTS)
variant_sequence_st = st.lists(variant_st, min_size=1, max_size=20)

nonempty_key_st = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N"), whitelist_characters="-_"),
    min_size=1,
    max_size=40,
).filter(lambda s: s.strip())

empty_key_st = st.sampled_from(["", None])


# ── Property 3: LLMPool Variant Tracking ─────────────────────────────────

class TestVariantTracking:
    """
    Property 3: For any sequence of get_medium_llm(variant) calls,
    _current_medium_variant always equals the variant of the most recent
    successful call. Cache hits don't trigger swaps. clear() resets to None.
    """

    @given(variants=variant_sequence_st)
    @settings(max_examples=200)
    @pytest.mark.anyio
    async def test_variant_tracks_last_call(self, variants):
        """_current_medium_variant matches the last requested variant."""
        with fresh_pool():
            LLMPool._swap_manager = AsyncMock()

            with patch("src.agent.llm.get_profile", return_value=PROFILE), \
                 patch("src.agent.llm.ChatOpenAI", return_value=MagicMock()):
                for v in variants:
                    await LLMPool.get_medium_llm(v)

            assert LLMPool._current_medium_variant == variants[-1]

    @given(variant=variant_st)
    @settings(max_examples=100)
    @pytest.mark.anyio
    async def test_cache_hit_no_swap(self, variant):
        """Requesting the already-loaded variant does not trigger a swap."""
        with fresh_pool():
            mock_swap = AsyncMock()
            LLMPool._swap_manager = mock_swap
            LLMPool._medium_llm = MagicMock()
            LLMPool._current_medium_variant = variant

            result = await LLMPool.get_medium_llm(variant)

            mock_swap.swap_model.assert_not_called()
            assert result is LLMPool._medium_llm

    @given(variants=st.lists(variant_st, min_size=2, max_size=10))
    @settings(max_examples=200)
    @pytest.mark.anyio
    async def test_swap_count_matches_variant_changes(self, variants):
        """swap_model is called only when the variant actually changes."""
        with fresh_pool():
            mock_swap = AsyncMock()
            LLMPool._swap_manager = mock_swap

            with patch("src.agent.llm.get_profile", return_value=PROFILE), \
                 patch("src.agent.llm.ChatOpenAI", return_value=MagicMock()):
                for v in variants:
                    await LLMPool.get_medium_llm(v)

            # First call always swaps (variant starts as None),
            # then only when variant differs from previous
            expected_swaps = 1
            for i in range(1, len(variants)):
                if variants[i] != variants[i - 1]:
                    expected_swaps += 1

            assert mock_swap.swap_model.call_count == expected_swaps

    @given(variants=variant_sequence_st)
    @settings(max_examples=100)
    @pytest.mark.anyio
    async def test_clear_resets_variant_to_none(self, variants):
        """After clear(), _current_medium_variant is None."""
        with fresh_pool():
            LLMPool._swap_manager = AsyncMock()

            with patch("src.agent.llm.get_profile", return_value=PROFILE), \
                 patch("src.agent.llm.ChatOpenAI", return_value=MagicMock()):
                for v in variants:
                    await LLMPool.get_medium_llm(v)

            LLMPool.clear()

            assert LLMPool._current_medium_variant is None
            assert LLMPool._medium_llm is None
            assert LLMPool._cloud_llm is None


# ── Property 10: API Key Resolution Order ────────────────────────────────

class TestAPIKeyResolution:
    """
    Property 10: env var > profile > disabled.
    If DEEPSEEK_API_KEY env var is set and non-empty, it is used.
    Otherwise the profile field is used. If neither, cloud is disabled.
    """

    @given(env_key=nonempty_key_st, profile_key=nonempty_key_st)
    @settings(max_examples=200)
    @pytest.mark.anyio
    async def test_env_var_takes_priority(self, env_key, profile_key):
        """When both env var and profile key exist, env var wins."""
        with fresh_pool():
            profile = {**PROFILE, "deepseek_api_key": profile_key}

            with patch("src.agent.llm.DEEPSEEK_API_KEY", env_key), \
                 patch("src.agent.llm.get_profile", return_value=profile), \
                 patch("src.agent.llm.ChatOpenAI") as MockChat:
                MockChat.return_value = MagicMock()
                await LLMPool.get_cloud_llm()

            assert MockChat.call_args[1]["api_key"] == env_key

    @given(profile_key=nonempty_key_st)
    @settings(max_examples=200)
    @pytest.mark.anyio
    async def test_profile_key_used_when_env_empty(self, profile_key):
        """When env var is empty, profile key is used."""
        with fresh_pool():
            profile = {**PROFILE, "deepseek_api_key": profile_key}

            with patch("src.agent.llm.DEEPSEEK_API_KEY", ""), \
                 patch("src.agent.llm.get_profile", return_value=profile), \
                 patch("src.agent.llm.ChatOpenAI") as MockChat:
                MockChat.return_value = MagicMock()
                await LLMPool.get_cloud_llm()

            assert MockChat.call_args[1]["api_key"] == profile_key

    @given(empty_env=empty_key_st)
    @settings(max_examples=100)
    @pytest.mark.anyio
    async def test_no_key_raises_cloud_unavailable(self, empty_env):
        """When neither env var nor profile has a key, CloudUnavailableError."""
        with fresh_pool():
            profile = {**PROFILE, "deepseek_api_key": ""}
            env_val = empty_env if empty_env is not None else ""

            with patch("src.agent.llm.DEEPSEEK_API_KEY", env_val), \
                 patch("src.agent.llm.get_profile", return_value=profile):
                with pytest.raises(CloudUnavailableError):
                    await LLMPool.get_cloud_llm()
