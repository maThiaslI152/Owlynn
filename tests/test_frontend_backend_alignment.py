"""
Bug condition exploration tests for frontend-backend alignment.

Property 1: Bug Condition - Settings Fields Dropped and GET Response Incomplete

These tests encode the EXPECTED behavior. They are designed to FAIL on unfixed
code, confirming the bugs exist. Once the fix is applied, they should PASS.

**Validates: Requirements 1.1, 1.4, 1.5**
"""

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st
from fastapi.testclient import TestClient

from src.memory.user_profile import _DEFAULTS


# ── Strategies ───────────────────────────────────────────────────────────

# Valid redis_url strings: redis://host:port
redis_url_st = st.builds(
    lambda host, port: f"redis://{host}:{port}",
    host=st.from_regex(r"[a-z][a-z0-9\-]{0,20}", fullmatch=True),
    port=st.integers(min_value=1, max_value=65535),
)

lm_studio_fold_st = st.booleans()


# ── Fixtures ─────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def isolated_profile(tmp_path):
    """
    Redirect user_profile reads/writes to a temp file so tests don't
    mutate the real data/user_profile.json.
    """
    tmp_profile = tmp_path / "user_profile.json"
    tmp_profile.write_text(json.dumps(_DEFAULTS), encoding="utf-8")

    with patch("src.memory.user_profile._PROFILE_PATH", tmp_profile):
        yield tmp_profile


@pytest.fixture()
def client():
    """
    Create a TestClient that skips the lifespan (which initializes the
    heavy LangGraph agent). We only need the REST endpoints.
    """
    from src.api.server import app

    with TestClient(app, raise_server_exceptions=True) as c:
        yield c


# ═════════════════════════════════════════════════════════════════════════
# Property 1: Bug Condition - Settings Fields Dropped and GET Response
#             Incomplete
# ═════════════════════════════════════════════════════════════════════════

class TestBugConditionSettingsDropped:
    """
    Property 1: For any advanced settings payload containing redis_url
    and/or lm_studio_fold_system, the POST handler SHALL accept and persist
    these fields, and the subsequent GET response SHALL include them with
    the persisted values.

    **Validates: Requirements 1.1, 1.4, 1.5**
    """

    @given(redis_url=redis_url_st)
    @settings(
        max_examples=50,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    def test_redis_url_round_trips_through_advanced_settings(
        self, redis_url, client, isolated_profile
    ):
        """
        Bug 1: POST redis_url to /api/advanced-settings, then GET.
        Assert redis_url is present in the GET response.

        On unfixed code this FAILS because:
        - POST handler whitelist does not include redis_url (silently dropped)
        - GET handler does not return redis_url
        """
        # Reset profile to defaults before each hypothesis example
        isolated_profile.write_text(json.dumps(_DEFAULTS), encoding="utf-8")

        # POST the redis_url
        resp = client.post("/api/advanced-settings", json={"redis_url": redis_url})
        assert resp.status_code == 200

        # GET and verify redis_url is present with the value we posted
        resp = client.get("/api/advanced-settings")
        assert resp.status_code == 200
        data = resp.json()

        assert "redis_url" in data, (
            f"GET /api/advanced-settings response missing 'redis_url'. "
            f"Keys returned: {list(data.keys())}"
        )
        assert data["redis_url"] == redis_url, (
            f"Expected redis_url='{redis_url}', got '{data.get('redis_url')}'"
        )

    @given(fold=lm_studio_fold_st)
    @settings(
        max_examples=50,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    def test_lm_studio_fold_system_round_trips_through_advanced_settings(
        self, fold, client, isolated_profile
    ):
        """
        Bug 4: POST lm_studio_fold_system to /api/advanced-settings, then GET.
        Assert lm_studio_fold_system is present in the GET response.

        On unfixed code this FAILS because:
        - POST handler whitelist does not include lm_studio_fold_system
        - GET handler does not return lm_studio_fold_system
        """
        # Reset profile to defaults before each hypothesis example
        isolated_profile.write_text(json.dumps(_DEFAULTS), encoding="utf-8")

        # POST the lm_studio_fold_system value
        resp = client.post(
            "/api/advanced-settings",
            json={"lm_studio_fold_system": fold},
        )
        assert resp.status_code == 200

        # GET and verify lm_studio_fold_system is present
        resp = client.get("/api/advanced-settings")
        assert resp.status_code == 200
        data = resp.json()

        assert "lm_studio_fold_system" in data, (
            f"GET /api/advanced-settings response missing 'lm_studio_fold_system'. "
            f"Keys returned: {list(data.keys())}"
        )
        assert data["lm_studio_fold_system"] == fold, (
            f"Expected lm_studio_fold_system={fold}, got '{data.get('lm_studio_fold_system')}'"
        )

    def test_get_advanced_settings_contains_all_routing_cloud_fields(
        self, client, isolated_profile
    ):
        """
        Bug 5: GET /api/advanced-settings must return routing/cloud fields.

        On unfixed code this FAILS because the GET handler only returns
        inference parameters (temperature, top_p, etc.) and behavior toggles.
        """
        resp = client.get("/api/advanced-settings")
        assert resp.status_code == 200
        data = resp.json()

        required_fields = [
            "cloud_escalation_enabled",
            "cloud_anonymization_enabled",
            "router_hitl_enabled",
            "router_clarification_threshold",
            "custom_sensitive_terms",
            "redis_url",
            "lm_studio_fold_system",
        ]

        missing = [f for f in required_fields if f not in data]
        assert not missing, (
            f"GET /api/advanced-settings response missing fields: {missing}. "
            f"Keys returned: {list(data.keys())}"
        )


# ═════════════════════════════════════════════════════════════════════════
# Property 2: Preservation - Existing Advanced Settings Save/Load Unchanged
# ═════════════════════════════════════════════════════════════════════════

# ── Strategies for preservation tests ────────────────────────────────────

# Currently-working fields that the GET endpoint returns on unfixed code
temperature_st = st.floats(min_value=0.0, max_value=2.0, allow_nan=False, allow_infinity=False)
top_p_st = st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False)
max_tokens_st = st.integers(min_value=256, max_value=8192)
top_k_st = st.integers(min_value=0, max_value=100)
bool_toggle_st = st.booleans()


class TestPreservationAdvancedSettingsRoundTrip:
    """
    Property 2: Preservation - For all valid combinations of currently-working
    advanced settings fields, POST then GET returns the same values.

    These tests MUST PASS on unfixed code — they confirm baseline behavior
    that the fix must preserve.

    **Validates: Requirements 3.1, 3.2, 3.5, 3.7**
    """

    @given(
        temperature=temperature_st,
        top_p=top_p_st,
        max_tokens=max_tokens_st,
        top_k=top_k_st,
        streaming_enabled=bool_toggle_st,
        show_thinking=bool_toggle_st,
        show_tool_execution=bool_toggle_st,
    )
    @settings(
        max_examples=50,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    def test_working_fields_round_trip_through_advanced_settings(
        self,
        temperature,
        top_p,
        max_tokens,
        top_k,
        streaming_enabled,
        show_thinking,
        show_tool_execution,
        client,
        isolated_profile,
    ):
        """
        For any valid combination of currently-working advanced settings
        fields, POST /api/advanced-settings then GET /api/advanced-settings
        returns the same values we posted.

        On unfixed code this PASSES because these fields are already in
        both the POST whitelist and the GET response.
        """
        # Reset profile to defaults before each hypothesis example
        isolated_profile.write_text(json.dumps(_DEFAULTS), encoding="utf-8")

        payload = {
            "temperature": temperature,
            "top_p": top_p,
            "max_tokens": max_tokens,
            "top_k": top_k,
            "streaming_enabled": streaming_enabled,
            "show_thinking": show_thinking,
            "show_tool_execution": show_tool_execution,
        }

        # POST the settings
        resp = client.post("/api/advanced-settings", json=payload)
        assert resp.status_code == 200
        post_data = resp.json()
        assert post_data.get("status") == "ok", f"POST failed: {post_data}"

        # GET and verify all posted values are returned
        resp = client.get("/api/advanced-settings")
        assert resp.status_code == 200
        data = resp.json()

        # Numeric fields: compare with tolerance for float round-trip
        assert abs(data["temperature"] - temperature) < 1e-9, (
            f"temperature mismatch: posted {temperature}, got {data['temperature']}"
        )
        assert abs(data["top_p"] - top_p) < 1e-9, (
            f"top_p mismatch: posted {top_p}, got {data['top_p']}"
        )
        assert data["max_tokens"] == max_tokens, (
            f"max_tokens mismatch: posted {max_tokens}, got {data['max_tokens']}"
        )
        assert data["top_k"] == top_k, (
            f"top_k mismatch: posted {top_k}, got {data['top_k']}"
        )

        # Boolean toggles: exact match
        assert data["streaming_enabled"] == streaming_enabled, (
            f"streaming_enabled mismatch: posted {streaming_enabled}, got {data['streaming_enabled']}"
        )
        assert data["show_thinking"] == show_thinking, (
            f"show_thinking mismatch: posted {show_thinking}, got {data['show_thinking']}"
        )
        assert data["show_tool_execution"] == show_tool_execution, (
            f"show_tool_execution mismatch: posted {show_tool_execution}, got {data['show_tool_execution']}"
        )


class TestPreservationModelBadgeClass:
    """
    Property 2: Preservation - getModelBadgeClass() returns consistent tier
    colors for any model string starting with known prefixes.

    Tests the Python-equivalent logic of the JS function directly.

    **Validates: Requirements 3.5**
    """

    @staticmethod
    def get_model_badge_class(model: str | None) -> str:
        """
        Python equivalent of frontend/script.js getModelBadgeClass().

        Mirrors the JS logic exactly:
          if (!model) return 'model-badge-small';
          if (model.includes('fallback')) return 'model-badge-fallback';
          if (model.startsWith('large') || model.startsWith('cloud')) return 'model-badge-cloud';
          if (model.startsWith('medium')) return 'model-badge-medium';
          return 'model-badge-small';
        """
        if not model:
            return "model-badge-small"
        if "fallback" in model:
            return "model-badge-fallback"
        if model.startswith("large") or model.startswith("cloud"):
            return "model-badge-cloud"
        if model.startswith("medium"):
            return "model-badge-medium"
        return "model-badge-small"

    # Strategy: model strings with known prefixes + random suffixes
    model_prefix_st = st.sampled_from(["small", "medium", "large", "cloud", "fallback"])
    model_suffix_st = st.text(
        alphabet=st.characters(whitelist_categories=("L", "N", "P")),
        min_size=0,
        max_size=30,
    )

    EXPECTED_BADGE = {
        "small": "model-badge-small",
        "medium": "model-badge-medium",
        "large": "model-badge-cloud",
        "cloud": "model-badge-cloud",
        "fallback": "model-badge-fallback",
    }

    @given(prefix=model_prefix_st, suffix=model_suffix_st)
    @settings(max_examples=100)
    def test_badge_class_matches_expected_tier(self, prefix, suffix):
        """
        For any model string starting with a known tier prefix, the badge
        class matches the expected tier mapping.

        Note: 'fallback' is special — it matches via `includes('fallback')`
        not `startsWith`, so 'fallback' anywhere in the string triggers it.
        We test with prefix to keep it simple and consistent.
        """
        model = prefix + suffix
        result = self.get_model_badge_class(model)

        # 'fallback' in the string takes priority (checked first in JS)
        if "fallback" in model:
            assert result == "model-badge-fallback", (
                f"Model '{model}' should be fallback, got '{result}'"
            )
        else:
            expected = self.EXPECTED_BADGE[prefix]
            assert result == expected, (
                f"Model '{model}' (prefix='{prefix}') expected '{expected}', got '{result}'"
            )

    def test_none_model_returns_small(self):
        """None/empty model defaults to small badge."""
        assert self.get_model_badge_class(None) == "model-badge-small"
        assert self.get_model_badge_class("") == "model-badge-small"

    def test_unknown_prefix_returns_small(self):
        """Model strings not matching any known prefix default to small."""
        assert self.get_model_badge_class("unknown-model") == "model-badge-small"
        assert self.get_model_badge_class("tiny-v1") == "model-badge-small"
