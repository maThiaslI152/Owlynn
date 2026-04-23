"""Unit tests for the refactored LLMPool in src/agent/llm.py."""

import sys
from unittest.mock import AsyncMock, MagicMock, patch

sys.modules["mem0"] = MagicMock()

import pytest

from src.agent.llm import CloudUnavailableError, LLMPool


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


@pytest.fixture(autouse=True)
def _clear_pool():
    """Reset LLMPool state before each test."""
    LLMPool.clear()
    LLMPool._swap_manager = None
    yield
    LLMPool.clear()
    LLMPool._swap_manager = None


def test_clear_resets_all_slots():
    LLMPool._small_llm = "fake"
    LLMPool._medium_llm = "fake"
    LLMPool._cloud_llm = "fake"
    LLMPool._current_medium_variant = "vision"

    LLMPool.clear()

    assert LLMPool._small_llm is None
    assert LLMPool._medium_llm is None
    assert LLMPool._cloud_llm is None
    assert LLMPool._current_medium_variant is None


@pytest.mark.anyio
async def test_get_medium_llm_cache_hit():
    """When variant matches, no swap is triggered."""
    mock_swap = AsyncMock()
    LLMPool._swap_manager = mock_swap

    fake_llm = MagicMock()
    LLMPool._medium_llm = fake_llm
    LLMPool._current_medium_variant = "default"

    result = await LLMPool.get_medium_llm("default")

    assert result is fake_llm
    mock_swap.swap_model.assert_not_called()


@pytest.mark.anyio
async def test_get_medium_llm_triggers_swap_on_variant_mismatch():
    """When variant differs, swap_model is called."""
    mock_swap = AsyncMock()
    LLMPool._swap_manager = mock_swap
    LLMPool._current_medium_variant = "default"

    with patch("src.agent.llm.get_profile", return_value=PROFILE), \
         patch("src.agent.llm.ChatOpenAI") as MockChat:
        MockChat.return_value = MagicMock()
        result = await LLMPool.get_medium_llm("vision")

    mock_swap.swap_model.assert_called_once_with("vision")
    assert LLMPool._current_medium_variant == "vision"


@pytest.mark.anyio
async def test_get_medium_llm_variant_tracking():
    """After sequential calls, _current_medium_variant tracks the last one."""
    mock_swap = AsyncMock()
    LLMPool._swap_manager = mock_swap

    with patch("src.agent.llm.get_profile", return_value=PROFILE), \
         patch("src.agent.llm.ChatOpenAI") as MockChat:
        MockChat.return_value = MagicMock()

        await LLMPool.get_medium_llm("default")
        assert LLMPool._current_medium_variant == "default"

        await LLMPool.get_medium_llm("vision")
        assert LLMPool._current_medium_variant == "vision"

        await LLMPool.get_medium_llm("longctx")
        assert LLMPool._current_medium_variant == "longctx"


@pytest.mark.anyio
async def test_get_cloud_llm_raises_without_api_key():
    """CloudUnavailableError when no API key is configured."""
    with patch("src.agent.llm.DEEPSEEK_API_KEY", ""), \
         patch("src.agent.llm.get_profile", return_value=PROFILE):
        with pytest.raises(CloudUnavailableError):
            await LLMPool.get_cloud_llm()


@pytest.mark.anyio
async def test_get_cloud_llm_uses_env_var_first():
    """Env var takes priority over profile key."""
    profile_with_key = {**PROFILE, "deepseek_api_key": "profile-key"}

    with patch("src.agent.llm.DEEPSEEK_API_KEY", "env-key"), \
         patch("src.agent.llm.get_profile", return_value=profile_with_key), \
         patch("src.agent.llm.ChatOpenAI") as MockChat:
        MockChat.return_value = MagicMock()
        await LLMPool.get_cloud_llm()

    # ChatOpenAI should have been called with the env key
    call_kwargs = MockChat.call_args[1]
    assert call_kwargs["api_key"] == "env-key"


@pytest.mark.anyio
async def test_get_cloud_llm_falls_back_to_profile_key():
    """Profile key used when env var is empty."""
    profile_with_key = {**PROFILE, "deepseek_api_key": "profile-key"}

    with patch("src.agent.llm.DEEPSEEK_API_KEY", ""), \
         patch("src.agent.llm.get_profile", return_value=profile_with_key), \
         patch("src.agent.llm.ChatOpenAI") as MockChat:
        MockChat.return_value = MagicMock()
        await LLMPool.get_cloud_llm()

    call_kwargs = MockChat.call_args[1]
    assert call_kwargs["api_key"] == "profile-key"


@pytest.mark.anyio
async def test_get_cloud_llm_config():
    """Cloud LLM has streaming=True, max_tokens=8192, no extra_body."""
    with patch("src.agent.llm.DEEPSEEK_API_KEY", "test-key"), \
         patch("src.agent.llm.get_profile", return_value=PROFILE), \
         patch("src.agent.llm.ChatOpenAI") as MockChat:
        MockChat.return_value = MagicMock()
        await LLMPool.get_cloud_llm()

    call_kwargs = MockChat.call_args[1]
    assert call_kwargs["streaming"] is True
    assert call_kwargs["max_tokens"] == 8192
    assert call_kwargs["temperature"] == 0.4
    assert "extra_body" not in call_kwargs


@pytest.mark.anyio
async def test_get_large_llm_is_alias():
    """get_large_llm() delegates to get_medium_llm('default')."""
    mock_swap = AsyncMock()
    LLMPool._swap_manager = mock_swap

    with patch("src.agent.llm.get_profile", return_value=PROFILE), \
         patch("src.agent.llm.ChatOpenAI") as MockChat:
        MockChat.return_value = MagicMock()
        result = await LLMPool.get_large_llm()

    assert LLMPool._current_medium_variant == "default"
