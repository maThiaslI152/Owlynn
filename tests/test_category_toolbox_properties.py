"""
Property-based tests for project category-to-toolbox resolution.

# Feature: productivity-workspace-overhaul, Property 14: Category-to-toolbox resolution
# **Validates: Requirements 6.2, 6.3, 6.4**

The CATEGORY_TOOLBOX_MAP (defined in frontend/modules/tool-dock.js) maps each
project category to a list of toolbox registry keys.  This test mirrors that
mapping in Python and verifies the following property:

    For any valid project category string, the CATEGORY_TOOLBOX_MAP resolution
    should return a non-empty list of tools that is a subset of the full tool
    registry.  For the category "general" or a null/missing category, it should
    return all available tools.
"""

import sys
from unittest.mock import MagicMock

# Mem0 may not be installed in the test environment
sys.modules["mem0"] = MagicMock()

from hypothesis import given, settings, assume
from hypothesis import strategies as st

from src.agent.tool_sets import (
    TOOLBOX_REGISTRY,
    ALWAYS_INCLUDED_TOOLS,
    COMPLEX_TOOLS_WITH_WEB,
    resolve_tools,
)

# ── Mirror of frontend CATEGORY_TOOLBOX_MAP (tool-dock.js) ───────────────
CATEGORY_TOOLBOX_MAP: dict[str, list[str]] = {
    "cybersec":    ["web_search", "file_ops"],
    "writing":     ["data_viz", "productivity"],
    "research":    ["web_search", "memory"],
    "development": ["file_ops", "data_viz", "productivity"],
    "data":        ["data_viz", "file_ops"],
    "general":     ["all"],
}

VALID_CATEGORIES = list(CATEGORY_TOOLBOX_MAP.keys())
VALID_TOOLBOX_NAMES = list(TOOLBOX_REGISTRY.keys())

# All tool ids in the full registry (union of every toolbox)
ALL_REGISTRY_TOOL_IDS = set()
for _tools in TOOLBOX_REGISTRY.values():
    for _t in _tools:
        ALL_REGISTRY_TOOL_IDS.add(id(_t))
for _t in ALWAYS_INCLUDED_TOOLS:
    ALL_REGISTRY_TOOL_IDS.add(id(_t))

# Full tool set ids (what "general" / null should resolve to)
FULL_TOOL_IDS = set(id(t) for t in COMPLEX_TOOLS_WITH_WEB)


def _resolve_category(category: str | None) -> list:
    """Resolve a project category to a tool list via CATEGORY_TOOLBOX_MAP + resolve_tools."""
    cat = (category or "general").lower()
    keys = CATEGORY_TOOLBOX_MAP.get(cat, CATEGORY_TOOLBOX_MAP["general"])
    return resolve_tools(keys)


# ── Strategies ───────────────────────────────────────────────────────────

valid_category_st = st.sampled_from(VALID_CATEGORIES)

# Null / missing category represented as None or empty string
null_category_st = st.sampled_from([None, "", "general"])


# ── Property 14: Category-to-toolbox resolution ─────────────────────────

class TestCategoryToolboxResolutionProperty:
    """
    Property 14: For any valid project category string, the
    CATEGORY_TOOLBOX_MAP resolution should return a non-empty list of tools
    that is a subset of the full tool registry.  For the category "general"
    or a null/missing category, it should return all available tools.

    **Validates: Requirements 6.2, 6.3, 6.4**
    """

    @given(category=valid_category_st)
    @settings(max_examples=200)
    def test_resolution_returns_non_empty(self, category):
        """Every valid category resolves to a non-empty tool list."""
        tools = _resolve_category(category)
        assert len(tools) > 0, f"Category '{category}' resolved to empty tool list"

    @given(category=valid_category_st)
    @settings(max_examples=200)
    def test_resolved_tools_are_subset_of_registry(self, category):
        """Resolved tools are a subset of the full tool registry + always-included."""
        tools = _resolve_category(category)
        tool_ids = set(id(t) for t in tools)
        # Every resolved tool must come from the registry or always-included
        assert tool_ids.issubset(ALL_REGISTRY_TOOL_IDS | FULL_TOOL_IDS), (
            f"Category '{category}' resolved tools not a subset of registry"
        )

    @given(category=null_category_st)
    @settings(max_examples=100)
    def test_general_or_null_returns_all_tools(self, category):
        """'general', None, or empty string resolves to the full tool set."""
        tools = _resolve_category(category)
        tool_ids = set(id(t) for t in tools)
        assert FULL_TOOL_IDS.issubset(tool_ids), (
            f"Category '{category}' did not return all available tools"
        )

    @given(category=valid_category_st)
    @settings(max_examples=200)
    def test_category_maps_to_valid_toolbox_keys(self, category):
        """Every key in CATEGORY_TOOLBOX_MAP maps to valid TOOLBOX_REGISTRY keys or 'all'."""
        keys = CATEGORY_TOOLBOX_MAP[category]
        for key in keys:
            assert key == "all" or key in TOOLBOX_REGISTRY, (
                f"Category '{category}' maps to unknown toolbox key '{key}'"
            )

    @given(category=valid_category_st)
    @settings(max_examples=200)
    def test_non_general_category_is_strict_subset(self, category):
        """Non-general categories resolve to a subset (not necessarily all) of tools."""
        tools = _resolve_category(category)
        tool_ids = set(id(t) for t in tools)
        if category != "general":
            # Should contain only tools from the mapped toolbox keys + always-included
            expected_ids = set()
            for key in CATEGORY_TOOLBOX_MAP[category]:
                if key in TOOLBOX_REGISTRY:
                    for t in TOOLBOX_REGISTRY[key]:
                        expected_ids.add(id(t))
            for t in ALWAYS_INCLUDED_TOOLS:
                expected_ids.add(id(t))
            assert tool_ids == expected_ids, (
                f"Category '{category}' resolved to unexpected tool set"
            )
