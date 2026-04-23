import re
from unittest.mock import patch

from fastapi.testclient import TestClient


class _DummyWatcher:
    def stop(self):
        return None

    def join(self):
        return None


class _DummyAgent:
    async def astream_events(self, _input_data, config=None, version="v2"):
        if False:
            yield {}


def test_root_serves_frontend_v2_index_and_assets():
    from src.api.server import app

    with patch("src.api.server.init_agent", autospec=True) as init_agent_mock, patch(
        "src.api.server.start_watcher", autospec=True
    ) as watcher_mock:
        init_agent_mock.return_value = _DummyAgent()
        watcher_mock.return_value = _DummyWatcher()

        with TestClient(app, raise_server_exceptions=True) as client:
            root = client.get("/")
            assert root.status_code == 200
            html = root.text
            assert "/assets/" in html

            asset_match = re.search(r'/assets/[^"\\\']+', html)
            assert asset_match, "Expected an /assets/... reference in index.html"
            asset_path = asset_match.group(0)
            asset_resp = client.get(asset_path)
            assert asset_resp.status_code == 200


def test_legacy_static_endpoints_are_retired():
    from src.api.server import app

    with patch("src.api.server.init_agent", autospec=True) as init_agent_mock, patch(
        "src.api.server.start_watcher", autospec=True
    ) as watcher_mock:
        init_agent_mock.return_value = _DummyAgent()
        watcher_mock.return_value = _DummyWatcher()

        with TestClient(app, raise_server_exceptions=True) as client:
            assert client.get("/script.js").status_code == 410
            assert client.get("/style.css").status_code == 410
            assert client.get("/vendor/anything.js").status_code == 410


def test_legacy_assets_are_not_served_via_static_mount():
    from src.api.server import app

    with patch("src.api.server.init_agent", autospec=True) as init_agent_mock, patch(
        "src.api.server.start_watcher", autospec=True
    ) as watcher_mock:
        init_agent_mock.return_value = _DummyAgent()
        watcher_mock.return_value = _DummyWatcher()

        with TestClient(app, raise_server_exceptions=True) as client:
            # Guard against accidental overlap with old frontend/ tree paths.
            assert client.get("/static/script.js").status_code == 404
            assert client.get("/static/style.css").status_code == 404
            assert client.get("/static/vendor/anything.js").status_code == 404
