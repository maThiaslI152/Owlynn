"""
Property-based tests for model badge color mapping.

# Feature: deepseek-hybrid-integration, Property 13: Model Badge Color Mapping
# Validates: Requirements 30.10, 30.11, 30.12, 30.13
"""

import pytest
from hypothesis import given, settings, assume
from hypothesis import strategies as st


# ── Python equivalent of frontend getModelBadgeClass ─────────────────────

def get_model_badge_class(model: str | None) -> str:
    """
    Python equivalent of the JavaScript getModelBadgeClass function.

    Maps a model_used string to a CSS badge class based on prefix/content:
      - None/empty       → 'model-badge-small'  (gray)
      - contains 'fallback' → 'model-badge-fallback' (orange)
      - starts with 'large' or 'cloud' → 'model-badge-cloud' (purple)
      - starts with 'medium' → 'model-badge-medium' (blue)
      - default           → 'model-badge-small'  (gray)
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


# ── Badge class → color mapping ──────────────────────────────────────────

BADGE_COLORS = {
    "model-badge-small": "#374151",     # gray
    "model-badge-medium": "#1e3a5f",    # blue
    "model-badge-cloud": "#2b2646",     # purple
    "model-badge-fallback": "#451a03",  # orange
}

VALID_BADGE_CLASSES = set(BADGE_COLORS.keys())

# ── Known model_used values from the system ──────────────────────────────

KNOWN_MODELS = [
    "small-local",
    "medium-default",
    "medium-vision",
    "medium-longctx",
    "large-cloud",
    "small-local-fallback",
    "medium-default-fallback",
    "medium-vision-fallback",
    "medium-longctx-fallback",
    "large-cloud-fallback",
]

# ── Strategies ───────────────────────────────────────────────────────────

# Known model values from the system
known_model_st = st.sampled_from(KNOWN_MODELS)

# Arbitrary suffix for generating prefixed strings
suffix_st = st.text(
    min_size=0,
    max_size=50,
    alphabet=st.characters(whitelist_categories=("L", "N", "P"), whitelist_characters="-_"),
)

# Models starting with "small"
small_model_st = st.builds(lambda s: "small" + s, suffix_st)

# Models starting with "medium" (without "fallback")
medium_model_st = st.builds(
    lambda s: "medium" + s, suffix_st
).filter(lambda m: "fallback" not in m)

# Models starting with "large" (without "fallback")
large_model_st = st.builds(
    lambda s: "large" + s, suffix_st
).filter(lambda m: "fallback" not in m)

# Models starting with "cloud" (without "fallback")
cloud_model_st = st.builds(
    lambda s: "cloud" + s, suffix_st
).filter(lambda m: "fallback" not in m)

# Models containing "fallback" anywhere
fallback_model_st = st.one_of(
    # prefix + "fallback" + suffix
    st.builds(lambda p, s: p + "fallback" + s, suffix_st, suffix_st),
    # known fallback variants
    st.sampled_from([m for m in KNOWN_MODELS if "fallback" in m]),
).filter(lambda m: "fallback" in m and len(m) > 0)

# Arbitrary non-empty model strings
arbitrary_model_st = st.text(
    min_size=1,
    max_size=100,
    alphabet=st.characters(whitelist_categories=("L", "N", "P"), whitelist_characters="-_./"),
)


# ═════════════════════════════════════════════════════════════════════════
# Property 13: Model Badge Color Mapping
# ═════════════════════════════════════════════════════════════════════════

class TestModelBadgeColorMapping:
    """
    Property 13: For any model_used string, the frontend badge color SHALL be
    determined by the prefix:
      - Starts with "small" → gray (model-badge-small)
      - Starts with "medium" → blue (model-badge-medium)
      - Starts with "large" → purple (model-badge-cloud)
      - Contains "fallback" → orange (model-badge-fallback)

    **Validates: Requirements 30.10, 30.11, 30.12, 30.13**
    """

    @given(model=small_model_st)
    @settings(max_examples=100)
    def test_small_prefix_maps_to_gray(self, model):
        """
        Req 30.10: model starting with "small" → gray (model-badge-small).
        Fallback takes priority if "fallback" is also present.
        """
        assume("fallback" not in model)
        badge = get_model_badge_class(model)
        assert badge == "model-badge-small", (
            f"Expected 'model-badge-small' for '{model}', got '{badge}'"
        )
        assert BADGE_COLORS[badge] == "#374151"

    @given(model=medium_model_st)
    @settings(max_examples=100)
    def test_medium_prefix_maps_to_blue(self, model):
        """
        Req 30.11: model starting with "medium" → blue (model-badge-medium).
        """
        badge = get_model_badge_class(model)
        assert badge == "model-badge-medium", (
            f"Expected 'model-badge-medium' for '{model}', got '{badge}'"
        )
        assert BADGE_COLORS[badge] == "#1e3a5f"

    @given(model=large_model_st)
    @settings(max_examples=100)
    def test_large_prefix_maps_to_purple(self, model):
        """
        Req 30.12: model starting with "large" → purple (model-badge-cloud).
        """
        badge = get_model_badge_class(model)
        assert badge == "model-badge-cloud", (
            f"Expected 'model-badge-cloud' for '{model}', got '{badge}'"
        )
        assert BADGE_COLORS[badge] == "#2b2646"

    @given(model=cloud_model_st)
    @settings(max_examples=100)
    def test_cloud_prefix_maps_to_purple(self, model):
        """
        Req 30.12: model starting with "cloud" also → purple (model-badge-cloud).
        """
        badge = get_model_badge_class(model)
        assert badge == "model-badge-cloud", (
            f"Expected 'model-badge-cloud' for '{model}', got '{badge}'"
        )
        assert BADGE_COLORS[badge] == "#2b2646"

    @given(model=fallback_model_st)
    @settings(max_examples=100)
    def test_fallback_maps_to_orange(self, model):
        """
        Req 30.13: model containing "fallback" → orange (model-badge-fallback).
        Fallback detection takes priority over prefix matching.
        """
        badge = get_model_badge_class(model)
        assert badge == "model-badge-fallback", (
            f"Expected 'model-badge-fallback' for '{model}', got '{badge}'"
        )
        assert BADGE_COLORS[badge] == "#451a03"

    @given(model=known_model_st)
    @settings(max_examples=100)
    def test_all_known_models_map_to_valid_badge(self, model):
        """
        Every known model_used value maps to a valid badge class.
        """
        badge = get_model_badge_class(model)
        assert badge in VALID_BADGE_CLASSES, (
            f"'{model}' mapped to unknown badge '{badge}'"
        )

    @given(model=arbitrary_model_st)
    @settings(max_examples=100)
    def test_output_always_valid_badge_class(self, model):
        """
        For any arbitrary model string, the output is always a valid badge class.
        """
        badge = get_model_badge_class(model)
        assert badge in VALID_BADGE_CLASSES, (
            f"'{model}' mapped to unknown badge '{badge}'"
        )

    def test_none_and_empty_default_to_small(self):
        """None and empty string default to model-badge-small (gray)."""
        assert get_model_badge_class(None) == "model-badge-small"
        assert get_model_badge_class("") == "model-badge-small"

    @given(model=fallback_model_st)
    @settings(max_examples=100)
    def test_fallback_priority_over_prefix(self, model):
        """
        "fallback" detection takes priority: even if the model starts with
        "medium", "large", or "small", containing "fallback" → orange.
        """
        badge = get_model_badge_class(model)
        assert badge == "model-badge-fallback"
