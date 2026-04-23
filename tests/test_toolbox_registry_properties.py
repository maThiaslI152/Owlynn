"""
Property-based tests for the ToolboxRegistry and resolve_tools.

# Feature: deepseek-hybrid-integration, Property 5: Resolve Tools Produces Correct Union
# Validates: Requirements 15.7, 15.8, 15.9, 15.10
"""

import sys
from unittest.mock import MagicMock

sys.modules["mem0"] = MagicMock()

from hypothesis import given, settings
from hypothesis import strategies as st

from src.agent.tool_sets import (
    TOOLBOX_REGISTRY,
    ALWAYS_INCLUDED_TOOLS,
    COMPLEX_TOOLS_WITH_WEB,
    COMPLEX_TOOLS_NO_WEB,
    resolve_tools,
)
from src.tools.ask_user import ask_user

# ── Valid toolbox names ──────────────────────────────────────────────────
VALID_TOOLBOX_NAMES = list(TOOLBOX_REGISTRY.keys())

# Web tools that should be excluded when web_search_enabled=False
WEB_TOOLS = set(id(t) for t in TOOLBOX_REGISTRY["web_search"])

# ── Strategies ───────────────────────────────────────────────────────────

# Arbitrary subset of valid toolbox names (may be empty)
toolbox_subset_st = st.lists(
    st.sampled_from(VALID_TOOLBOX_NAMES),
    min_size=0,
    max_size=len(VALID_TOOLBOX_NAMES),
    unique=True,
)

web_enabled_st = st.booleans()


# ── Property 5: Resolve Tools Produces Correct Union ─────────────────────

class TestResolveToolsProperty:
    """
    Property 5: For any subset of valid toolbox names and any web_search_enabled
    boolean, resolve_tools returns the union of requested toolboxes plus ask_user.
    'all' returns the full set. web_search_enabled=False excludes web tools.
    """

    @given(toolbox_names=toolbox_subset_st, web_enabled=web_enabled_st)
    @settings(max_examples=200)
    def test_union_contains_all_requested_tools(self, toolbox_names, web_enabled):
        """Resolved tools contain every tool from every requested toolbox
        (except web tools when disabled)."""
        result = resolve_tools(toolbox_names, web_search_enabled=web_enabled)
        result_ids = set(id(t) for t in result)

        for name in toolbox_names:
            if name == "web_search" and not web_enabled:
                continue
            for tool in TOOLBOX_REGISTRY[name]:
                assert id(tool) in result_ids, (
                    f"Tool from toolbox '{name}' missing in resolve_tools result"
                )

    @given(toolbox_names=toolbox_subset_st, web_enabled=web_enabled_st)
    @settings(max_examples=200)
    def test_ask_user_always_included(self, toolbox_names, web_enabled):
        """ask_user is present in every resolve_tools result."""
        result = resolve_tools(toolbox_names, web_search_enabled=web_enabled)
        assert ask_user in result

    @given(toolbox_names=toolbox_subset_st, web_enabled=web_enabled_st)
    @settings(max_examples=200)
    def test_no_duplicates(self, toolbox_names, web_enabled):
        """Resolved tool list contains no duplicate tool objects."""
        result = resolve_tools(toolbox_names, web_search_enabled=web_enabled)
        result_ids = [id(t) for t in result]
        assert len(result_ids) == len(set(result_ids)), "Duplicate tools in result"

    @given(web_enabled=web_enabled_st)
    @settings(max_examples=100)
    def test_all_returns_full_set(self, web_enabled):
        """'all' in toolbox names returns the full tool set."""
        result = resolve_tools(["all"], web_search_enabled=web_enabled)
        expected = COMPLEX_TOOLS_WITH_WEB if web_enabled else COMPLEX_TOOLS_NO_WEB
        expected_ids = set(id(t) for t in expected)
        result_ids = set(id(t) for t in result)
        assert expected_ids.issubset(result_ids), (
            "Full tool set not returned when 'all' requested"
        )

    @given(toolbox_names=toolbox_subset_st)
    @settings(max_examples=200)
    def test_web_disabled_excludes_web_tools(self, toolbox_names):
        """When web_search_enabled=False, web tools never appear."""
        result = resolve_tools(toolbox_names, web_search_enabled=False)
        result_ids = set(id(t) for t in result)
        assert not result_ids.intersection(WEB_TOOLS), (
            "Web tools present despite web_search_enabled=False"
        )

    @given(toolbox_names=toolbox_subset_st)
    @settings(max_examples=200)
    def test_result_only_contains_requested_or_always_included(self, toolbox_names):
        """Every tool in the result belongs to a requested toolbox or ALWAYS_INCLUDED."""
        if not toolbox_names:
            return  # empty list falls back to 'all', skip this check

        result = resolve_tools(toolbox_names, web_search_enabled=True)
        allowed_ids = set(id(t) for t in ALWAYS_INCLUDED_TOOLS)
        for name in toolbox_names:
            for tool in TOOLBOX_REGISTRY[name]:
                allowed_ids.add(id(tool))

        for tool in result:
            assert id(tool) in allowed_ids, (
                f"Unexpected tool in result not from requested toolboxes"
            )
