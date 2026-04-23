import json
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage, AIMessageChunk

from src.memory.user_profile import get_profile
from src.memory.user_profile import _DEFAULTS


class _DummyWatcher:
    def stop(self):
        return None

    def join(self):
        return None


class _FakeAgent:
    async def astream_events(self, _input_data, config=None, version="v2"):
        profile = get_profile()
        model_key = profile.get("small_llm_model_name", "unknown-model")
        yield {
            "event": "on_chat_model_stream",
            "metadata": {"langgraph_node": "simple"},
            "data": {"chunk": AIMessageChunk(content="hello")},
        }
        yield {
            "event": "on_chain_end",
            "metadata": {"langgraph_node": "simple"},
            "data": {
                "output": {
                    "messages": [AIMessage(content="hello from fake agent")],
                    "model_used": model_key,
                }
            },
        }


@pytest.fixture()
def client(tmp_path):
    from src.api.server import app
    fake_agent = _FakeAgent()
    tmp_profile = tmp_path / "user_profile.json"
    tmp_profile.write_text(json.dumps(_DEFAULTS), encoding="utf-8")
    with patch("src.memory.user_profile._PROFILE_PATH", tmp_profile), patch(
        "src.api.server.init_agent", autospec=True
    ) as init_agent_mock, patch(
        "src.api.server.start_watcher", autospec=True
    ) as watcher_mock:
        init_agent_mock.return_value = fake_agent
        watcher_mock.return_value = _DummyWatcher()
        with TestClient(app, raise_server_exceptions=True) as c:
            yield c


def _collect_ws_events(ws, max_events=40):
    events = []
    for _ in range(max_events):
        event = ws.receive_json()
        events.append(event)
        if event.get("type") == "status" and event.get("content") == "idle":
            break
    return events


def test_websocket_uses_updated_model_key_after_profile_post(client):
    new_model = "gemma-4-e2b-heretic-uncensored-mlx"
    resp = client.post("/api/profile", json={"small_llm_model_name": new_model})
    assert resp.status_code == 200

    with client.websocket_connect("/ws/chat/test-model-update") as ws:
        ws.send_text(json.dumps({"message": "hello", "mode": "tools_on", "web_search_enabled": False}))
        events = _collect_ws_events(ws)

    model_info_events = [e for e in events if e.get("type") == "model_info"]
    assert model_info_events, f"No model_info events found in {events}"
    assert model_info_events[-1].get("model") == new_model


def test_websocket_run_does_not_emit_legacy_model_key_after_update(client):
    legacy = "liquid/lfm2.5-1.2b"
    new_model = "gemma-4-e2b-heretic-uncensored-mlx"
    resp = client.post("/api/profile", json={"small_llm_model_name": new_model})
    assert resp.status_code == 200

    with client.websocket_connect("/ws/chat/test-model-no-stale") as ws:
        ws.send_text(json.dumps({"message": "hello again", "mode": "tools_on", "web_search_enabled": False}))
        events = _collect_ws_events(ws)

    model_info_models = [e.get("model") for e in events if e.get("type") == "model_info"]
    assert model_info_models, f"No model_info events found in {events}"
    assert legacy not in model_info_models
    assert new_model in model_info_models
