"""
Unit tests for GET /api/unified-settings endpoint.

Validates: Requirements 1.1, 1.2, 1.3, 1.4, 1.5, 10.1, 10.2, 10.3
"""

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from src.memory.user_profile import _DEFAULTS


@pytest.fixture(autouse=True)
def isolated_profile(tmp_path):
    tmp_profile = tmp_path / "user_profile.json"
    tmp_profile.write_text(json.dumps(_DEFAULTS), encoding="utf-8")
    with patch("src.memory.user_profile._PROFILE_PATH", tmp_profile):
        yield tmp_profile


@pytest.fixture()
def client():
    from src.api.server import app
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c


class TestUnifiedSettings:
    """Tests for the GET /api/unified-settings endpoint."""

    def test_returns_200(self, client):
        resp = client.get("/api/unified-settings")
        assert resp.status_code == 200

    def test_contains_profile_identity_fields(self, client):
        data = client.get("/api/unified-settings").json()
        for field in ["name", "preferred_language", "response_style"]:
            assert field in data, f"Missing profile identity field: {field}"

    def test_contains_llm_config_fields(self, client):
        data = client.get("/api/unified-settings").json()
        for field in [
            "small_llm_base_url", "small_llm_model_name",
            "llm_base_url", "llm_model_name", "medium_models",
            "cloud_llm_base_url", "cloud_llm_model_name",
        ]:
            assert field in data, f"Missing LLM config field: {field}"

    def test_contains_inference_params(self, client):
        data = client.get("/api/unified-settings").json()
        for field in [
            "temperature", "top_p", "max_tokens", "top_k",
            "streaming_enabled", "show_thinking", "show_tool_execution",
            "lm_studio_fold_system",
        ]:
            assert field in data, f"Missing inference param: {field}"

    def test_contains_routing_cloud_fields(self, client):
        data = client.get("/api/unified-settings").json()
        for field in [
            "cloud_escalation_enabled", "cloud_anonymization_enabled",
            "router_hitl_enabled", "router_clarification_threshold",
            "custom_sensitive_terms", "redis_url", "execution_policy",
        ]:
            assert field in data, f"Missing routing/cloud field: {field}"

    def test_contains_cloud_budget_fields_with_defaults(self, client):
        data = client.get("/api/unified-settings").json()
        assert data["cloud_daily_token_limit"] == 500_000
        assert data["cloud_budget_warning_thresholds"] == [0.5, 0.8, 0.95]

    def test_deepseek_api_key_masked_when_present(self, client, isolated_profile):
        profile = json.loads(isolated_profile.read_text())
        profile["deepseek_api_key"] = "sk-secret-key-12345"
        isolated_profile.write_text(json.dumps(profile))

        data = client.get("/api/unified-settings").json()
        assert data["deepseek_api_key"] == "••••••••"
        assert "sk-secret-key-12345" not in json.dumps(data)

    def test_deepseek_api_key_empty_when_absent(self, client):
        data = client.get("/api/unified-settings").json()
        assert data["deepseek_api_key"] == ""

    def test_superset_of_advanced_settings(self, client):
        unified = client.get("/api/unified-settings").json()
        advanced = client.get("/api/advanced-settings").json()
        for key in advanced:
            assert key in unified, f"Unified missing advanced-settings field: {key}"

    def test_existing_endpoints_unchanged(self, client):
        profile_resp = client.get("/api/profile")
        advanced_resp = client.get("/api/advanced-settings")
        assert profile_resp.status_code == 200
        assert advanced_resp.status_code == 200

    def test_error_returns_error_dict(self):
        from src.api.server import app
        with patch("src.api.server.get_profile", side_effect=RuntimeError("boom")):
            with TestClient(app, raise_server_exceptions=False) as c:
                data = c.get("/api/unified-settings").json()
                assert "error" in data
                assert "boom" in data["error"]


class TestProfileUpdateRuntimeBehavior:
    def test_post_profile_updates_medium_models_round_trip(self, client):
        payload = {
            "medium_models": {
                "default": "lfm2-8b-a1b-absolute-heresy-mpoa-mlx",
                "vision": "zai-org/glm-4.6v-flash",
                "longctx": "lfm2-8b-a1b",
            }
        }
        resp = client.post("/api/profile", json=payload)
        assert resp.status_code == 200
        data = client.get("/api/profile").json()
        assert data["medium_models"] == payload["medium_models"]

    def test_post_profile_clears_llm_pool_for_runtime_fields(self, client):
        with patch("src.api.server.LLMPool.clear") as clear_mock:
            resp = client.post("/api/profile", json={"llm_base_url": "http://127.0.0.1:9999/v1"})
            assert resp.status_code == 200
            clear_mock.assert_called_once()

    def test_post_profile_sensitive_update_resets_cached_llm_instances(self, client):
        from src.agent.llm import LLMPool
        old_small = LLMPool._small_llm
        old_medium = LLMPool._medium_llm
        try:
            LLMPool._small_llm = object()
            LLMPool._medium_llm = object()
            resp = client.post("/api/profile", json={"small_llm_model_name": "gemma-4-e2b-heretic-uncensored-mlx"})
            assert resp.status_code == 200
            assert LLMPool._small_llm is None
            assert LLMPool._medium_llm is None
        finally:
            LLMPool._small_llm = old_small
            LLMPool._medium_llm = old_medium

    def test_post_profile_does_not_clear_llm_pool_for_non_sensitive_fields(self, client):
        with patch("src.api.server.LLMPool.clear") as clear_mock:
            resp = client.post("/api/profile", json={"name": "Test User"})
            assert resp.status_code == 200
            clear_mock.assert_not_called()

    def test_post_profile_returns_partial_success_with_errors(self, client):
        resp = client.post(
            "/api/profile",
            json={
                "name": "Updated",
                "definitely_unknown_field": "oops",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "partial_success"
        assert "definitely_unknown_field" in data["errors"]
        assert "name" in data["updated_fields"]
        assert data["profile"]["name"] == "Updated"
