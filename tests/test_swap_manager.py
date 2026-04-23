"""Unit tests for src/agent/swap_manager.py."""

import sys
from unittest.mock import AsyncMock, MagicMock, patch

sys.modules["mem0"] = MagicMock()

import pytest
import httpx

from src.agent.swap_manager import ModelSwapError, SwapManager


# ── helpers ──────────────────────────────────────────────────────────────

MEDIUM_MODELS = {
    "default": "qwen/qwen3.5-9b",
    "vision": "zai-org/glm-4.6v-flash",
    "longctx": "LFM2 8B A1B GGUF Q8_0",
}

PROFILE = {"medium_models": MEDIUM_MODELS}


def _models_response(loaded_key: str | None = None) -> dict:
    """Build a fake GET /api/v1/models response."""
    models = []
    for key in MEDIUM_MODELS.values():
        entry = {"key": key, "loaded_instances": []}
        if key == loaded_key:
            entry["loaded_instances"] = [{"id": f"inst-{key[:8]}"}]
        models.append(entry)
    return {"models": models}


# ── tests ────────────────────────────────────────────────────────────────

def test_get_current_variant_initially_none():
    sm = SwapManager()
    assert sm.get_current_variant() is None


@pytest.mark.anyio
async def test_get_loaded_instance_ids_returns_ids():
    sm = SwapManager()
    resp = MagicMock()
    resp.status_code = 200
    resp.raise_for_status = MagicMock()
    resp.json.return_value = _models_response(loaded_key="qwen/qwen3.5-9b")

    sm._client = AsyncMock()
    sm._client.get = AsyncMock(return_value=resp)

    ids = await sm.get_loaded_instance_ids("qwen/qwen3.5-9b")
    assert ids == ["inst-qwen/qwe"]


@pytest.mark.anyio
async def test_get_loaded_instance_ids_empty_when_not_loaded():
    sm = SwapManager()
    resp = MagicMock()
    resp.status_code = 200
    resp.raise_for_status = MagicMock()
    resp.json.return_value = _models_response(loaded_key=None)

    sm._client = AsyncMock()
    sm._client.get = AsyncMock(return_value=resp)

    ids = await sm.get_loaded_instance_ids("qwen/qwen3.5-9b")
    assert ids == []


@pytest.mark.anyio
async def test_swap_model_raises_on_unknown_variant():
    sm = SwapManager()
    with patch("src.agent.swap_manager.get_profile", return_value=PROFILE):
        with pytest.raises(ModelSwapError, match="No model key configured"):
            await sm.swap_model("nonexistent")


@pytest.mark.anyio
async def test_swap_model_success():
    """Happy path: unload current, load target, poll succeeds."""
    sm = SwapManager()
    target = "vision"
    target_key = MEDIUM_MODELS[target]

    # Mock HTTP responses
    get_resp_empty = MagicMock()
    get_resp_empty.status_code = 200
    get_resp_empty.raise_for_status = MagicMock()
    get_resp_empty.json.return_value = _models_response(loaded_key=None)

    get_resp_loaded = MagicMock()
    get_resp_loaded.status_code = 200
    get_resp_loaded.raise_for_status = MagicMock()
    get_resp_loaded.json.return_value = _models_response(loaded_key=target_key)

    post_resp_ok = MagicMock()
    post_resp_ok.status_code = 200
    post_resp_ok.text = "OK"

    call_count = 0

    async def mock_get(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        # First calls are for unload (get_loaded_instance_ids), return empty
        # Later calls are for polling, return loaded on second poll
        if call_count <= len(MEDIUM_MODELS):
            return get_resp_empty
        return get_resp_loaded

    client = AsyncMock()
    client.get = mock_get
    client.post = AsyncMock(return_value=post_resp_ok)
    sm._client = client

    with patch("src.agent.swap_manager.get_profile", return_value=PROFILE), \
         patch("src.agent.swap_manager.asyncio.sleep", new_callable=AsyncMock):
        await sm.swap_model(target)

    assert sm.get_current_variant() == "vision"


@pytest.mark.anyio
async def test_swap_model_timeout_raises():
    """When polling never finds the model, ModelSwapError is raised."""
    sm = SwapManager()

    get_resp_empty = MagicMock()
    get_resp_empty.status_code = 200
    get_resp_empty.raise_for_status = MagicMock()
    get_resp_empty.json.return_value = _models_response(loaded_key=None)

    post_resp_ok = MagicMock()
    post_resp_ok.status_code = 200
    post_resp_ok.text = "OK"

    client = AsyncMock()
    client.get = AsyncMock(return_value=get_resp_empty)
    client.post = AsyncMock(return_value=post_resp_ok)
    sm._client = client

    # Patch timeout to 0 so it immediately times out
    swap_cfg = {"swap_timeout": 0, "poll_interval": 0}
    patched_opt = {"medium_models": swap_cfg}

    with patch("src.agent.swap_manager.get_profile", return_value=PROFILE), \
         patch("src.agent.swap_manager.M4_MAC_OPTIMIZATION", patched_opt):
        with pytest.raises(ModelSwapError, match="did not appear"):
            await sm.swap_model("default")


@pytest.mark.anyio
async def test_swap_model_unload_failure_continues():
    """If unload fails, swap should still attempt to load."""
    sm = SwapManager()
    target_key = MEDIUM_MODELS["default"]

    # get returns a model with loaded instance (so unload is attempted)
    get_resp_with_instance = MagicMock()
    get_resp_with_instance.status_code = 200
    get_resp_with_instance.raise_for_status = MagicMock()
    get_resp_with_instance.json.return_value = _models_response(loaded_key=target_key)

    # unload fails
    post_unload_fail = MagicMock()
    post_unload_fail.status_code = 500
    post_unload_fail.text = "Internal error"

    # load succeeds
    post_load_ok = MagicMock()
    post_load_ok.status_code = 200
    post_load_ok.text = "OK"

    call_count = {"get": 0, "post": 0}

    async def mock_get(*args, **kwargs):
        call_count["get"] += 1
        return get_resp_with_instance

    async def mock_post(url, **kwargs):
        call_count["post"] += 1
        if "unload" in url:
            return post_unload_fail
        return post_load_ok

    client = AsyncMock()
    client.get = mock_get
    client.post = mock_post
    sm._client = client

    with patch("src.agent.swap_manager.get_profile", return_value=PROFILE), \
         patch("src.agent.swap_manager.asyncio.sleep", new_callable=AsyncMock):
        await sm.swap_model("default")

    assert sm.get_current_variant() == "default"
