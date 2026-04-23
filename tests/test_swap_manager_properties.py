"""
Property-based tests for the SwapManager variant-to-key mapping.

# Feature: deepseek-hybrid-integration, Property 9: Swap Manager Variant-to-Key Mapping
# Validates: Requirements 3.1
"""

import sys
from unittest.mock import AsyncMock, MagicMock, patch

sys.modules["mem0"] = MagicMock()

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from src.agent.swap_manager import ModelSwapError, SwapManager

# ── Constants ────────────────────────────────────────────────────────────

VALID_VARIANTS = ["default", "vision", "longctx"]

DEFAULT_MEDIUM_MODELS = {
    "default": "qwen/qwen3.5-9b",
    "vision": "zai-org/glm-4.6v-flash",
    "longctx": "LFM2 8B A1B GGUF Q8_0",
}

# ── Strategies ───────────────────────────────────────────────────────────

variant_st = st.sampled_from(VALID_VARIANTS)

# Generate arbitrary non-empty model key strings for custom profiles
model_key_st = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N"), whitelist_characters="-_./"),
    min_size=1,
    max_size=60,
).filter(lambda s: s.strip())

# Generate a medium_models dict with arbitrary model keys per variant
custom_medium_models_st = st.fixed_dictionaries({
    "default": model_key_st,
    "vision": model_key_st,
    "longctx": model_key_st,
})


# ── Helpers ──────────────────────────────────────────────────────────────

def _make_models_response(loaded_key: str) -> dict:
    """Fake GET /api/v1/models response with *loaded_key* loaded."""
    return {
        "models": [
            {
                "key": loaded_key,
                "loaded_instances": [{"id": f"inst-{loaded_key[:12]}"}],
            }
        ]
    }


def _mock_client(target_key: str) -> AsyncMock:
    """Return an httpx AsyncClient mock that simulates a successful swap."""
    get_resp_empty = MagicMock()
    get_resp_empty.status_code = 200
    get_resp_empty.raise_for_status = MagicMock()
    get_resp_empty.json.return_value = {"models": []}

    get_resp_loaded = MagicMock()
    get_resp_loaded.status_code = 200
    get_resp_loaded.raise_for_status = MagicMock()
    get_resp_loaded.json.return_value = _make_models_response(target_key)

    post_resp = MagicMock()
    post_resp.status_code = 200
    post_resp.text = "OK"

    call_count = {"get": 0}

    async def mock_get(*args, **kwargs):
        call_count["get"] += 1
        # First calls are for unload queries (return empty), then poll returns loaded
        if call_count["get"] <= 3:
            return get_resp_empty
        return get_resp_loaded

    client = AsyncMock()
    client.get = mock_get
    client.post = AsyncMock(return_value=post_resp)
    return client


# ── Property 9: Swap Manager Variant-to-Key Mapping ─────────────────────

class TestVariantToKeyMapping:
    """
    Property 9: For any valid variant name ("default", "vision", "longctx"),
    the SwapManager SHALL use the model key from
    User_Profile["medium_models"][variant] when calling the LM Studio load API.
    """

    @given(variant=variant_st)
    @settings(max_examples=100)
    @pytest.mark.anyio
    async def test_swap_uses_correct_model_key_from_profile(self, variant):
        """swap_model(variant) sends the correct model key to the load endpoint."""
        expected_key = DEFAULT_MEDIUM_MODELS[variant]
        profile = {"medium_models": DEFAULT_MEDIUM_MODELS}

        sm = SwapManager()
        sm._client = _mock_client(expected_key)

        with patch("src.agent.swap_manager.get_profile", return_value=profile), \
             patch("src.agent.swap_manager.asyncio.sleep", new_callable=AsyncMock):
            await sm.swap_model(variant)

        # Verify the POST /api/v1/models/load was called with the right key
        load_calls = [
            c for c in sm._client.post.call_args_list
            if "load" in str(c)
        ]
        assert len(load_calls) == 1
        assert load_calls[0].kwargs.get("json", {}).get("model") == expected_key

    @given(variant=variant_st, medium_models=custom_medium_models_st)
    @settings(max_examples=200)
    @pytest.mark.anyio
    async def test_swap_uses_custom_model_keys(self, variant, medium_models):
        """With arbitrary model keys in the profile, the correct key is used."""
        expected_key = medium_models[variant]
        profile = {"medium_models": medium_models}

        sm = SwapManager()
        sm._client = _mock_client(expected_key)

        with patch("src.agent.swap_manager.get_profile", return_value=profile), \
             patch("src.agent.swap_manager.asyncio.sleep", new_callable=AsyncMock):
            await sm.swap_model(variant)

        load_calls = [
            c for c in sm._client.post.call_args_list
            if "load" in str(c)
        ]
        assert len(load_calls) == 1
        assert load_calls[0].kwargs.get("json", {}).get("model") == expected_key

    @given(variant=variant_st)
    @settings(max_examples=100)
    @pytest.mark.anyio
    async def test_variant_tracked_after_successful_swap(self, variant):
        """After a successful swap, get_current_variant() returns the variant."""
        profile = {"medium_models": DEFAULT_MEDIUM_MODELS}
        target_key = DEFAULT_MEDIUM_MODELS[variant]

        sm = SwapManager()
        sm._client = _mock_client(target_key)

        with patch("src.agent.swap_manager.get_profile", return_value=profile), \
             patch("src.agent.swap_manager.asyncio.sleep", new_callable=AsyncMock):
            await sm.swap_model(variant)

        assert sm.get_current_variant() == variant

    @given(
        variant=variant_st,
        invalid_variant=st.text(min_size=1, max_size=20).filter(
            lambda s: s not in VALID_VARIANTS
        ),
    )
    @settings(max_examples=100)
    @pytest.mark.anyio
    async def test_invalid_variant_raises_model_swap_error(self, variant, invalid_variant):
        """Variants not in medium_models raise ModelSwapError."""
        profile = {"medium_models": DEFAULT_MEDIUM_MODELS}

        sm = SwapManager()

        with patch("src.agent.swap_manager.get_profile", return_value=profile):
            with pytest.raises(ModelSwapError, match="No model key configured"):
                await sm.swap_model(invalid_variant)

    @given(variant=variant_st, medium_models=custom_medium_models_st)
    @settings(max_examples=100)
    @pytest.mark.anyio
    async def test_mapping_is_identity_on_profile(self, variant, medium_models):
        """The key sent to LM Studio is exactly medium_models[variant], no transformation."""
        expected_key = medium_models[variant]
        profile = {"medium_models": medium_models}

        sm = SwapManager()
        sm._client = _mock_client(expected_key)

        with patch("src.agent.swap_manager.get_profile", return_value=profile), \
             patch("src.agent.swap_manager.asyncio.sleep", new_callable=AsyncMock):
            await sm.swap_model(variant)

        load_calls = [
            c for c in sm._client.post.call_args_list
            if "load" in str(c)
        ]
        sent_key = load_calls[0].kwargs.get("json", {}).get("model")
        # The key must be the exact value from the profile, not transformed
        assert sent_key == expected_key
        assert sent_key is not None
