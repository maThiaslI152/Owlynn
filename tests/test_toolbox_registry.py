"""Unit tests for the ToolboxRegistry and resolve_tools in src/agent/tool_sets.py."""

import sys
from unittest.mock import MagicMock

sys.modules["mem0"] = MagicMock()

from src.agent.tool_sets import (
    TOOLBOX_REGISTRY,
    ALWAYS_INCLUDED_TOOLS,
    resolve_tools,
    COMPLEX_TOOLS_WITH_WEB,
    COMPLEX_TOOLS_NO_WEB,
)
from src.tools.ask_user import ask_user


class TestResolveToolsSingleToolbox:
    """Each toolbox name returns the correct tools."""

    def test_web_search_toolbox(self):
        tools = resolve_tools(["web_search"])
        for t in TOOLBOX_REGISTRY["web_search"]:
            assert t in tools

    def test_file_ops_toolbox(self):
        tools = resolve_tools(["file_ops"])
        for t in TOOLBOX_REGISTRY["file_ops"]:
            assert t in tools

    def test_data_viz_toolbox(self):
        tools = resolve_tools(["data_viz"])
        for t in TOOLBOX_REGISTRY["data_viz"]:
            assert t in tools

    def test_productivity_toolbox(self):
        tools = resolve_tools(["productivity"])
        for t in TOOLBOX_REGISTRY["productivity"]:
            assert t in tools

    def test_memory_toolbox(self):
        tools = resolve_tools(["memory"])
        for t in TOOLBOX_REGISTRY["memory"]:
            assert t in tools


class TestResolveToolsAll:
    """'all' returns the full tool set."""

    def test_all_returns_full_set(self):
        tools = resolve_tools(["all"])
        assert len(tools) >= len(COMPLEX_TOOLS_WITH_WEB)

    def test_all_with_web_enabled(self):
        tools = resolve_tools(["all"], web_search_enabled=True)
        # Should include web tools
        for t in TOOLBOX_REGISTRY["web_search"]:
            assert t in tools

    def test_all_with_web_disabled(self):
        tools = resolve_tools(["all"], web_search_enabled=False)
        # Should exclude web tools
        for t in TOOLBOX_REGISTRY["web_search"]:
            assert t not in tools


class TestResolveToolsWebSearchDisabled:
    """web_search_enabled=False excludes web tools."""

    def test_web_search_excluded_when_disabled(self):
        tools = resolve_tools(["web_search"], web_search_enabled=False)
        for t in TOOLBOX_REGISTRY["web_search"]:
            assert t not in tools

    def test_other_toolboxes_unaffected_when_web_disabled(self):
        tools = resolve_tools(["file_ops"], web_search_enabled=False)
        for t in TOOLBOX_REGISTRY["file_ops"]:
            assert t in tools


class TestAskUserAlwaysIncluded:
    """ask_user is always included regardless of selection."""

    def test_ask_user_in_single_toolbox(self):
        tools = resolve_tools(["memory"])
        assert ask_user in tools

    def test_ask_user_in_all(self):
        tools = resolve_tools(["all"])
        assert ask_user in tools

    def test_ask_user_when_web_disabled(self):
        tools = resolve_tools(["web_search"], web_search_enabled=False)
        assert ask_user in tools

    def test_ask_user_in_empty_list(self):
        tools = resolve_tools([])
        assert ask_user in tools


class TestResolveToolsMultipleToolboxes:
    """Multiple toolboxes return the union."""

    def test_union_of_two_toolboxes(self):
        tools = resolve_tools(["web_search", "file_ops"])
        for t in TOOLBOX_REGISTRY["web_search"]:
            assert t in tools
        for t in TOOLBOX_REGISTRY["file_ops"]:
            assert t in tools

    def test_union_of_all_toolboxes(self):
        all_names = list(TOOLBOX_REGISTRY.keys())
        tools = resolve_tools(all_names)
        for name in all_names:
            for t in TOOLBOX_REGISTRY[name]:
                assert t in tools


class TestResolveToolsEmptyList:
    """Empty list returns full set (same as 'all')."""

    def test_empty_list_returns_full_set(self):
        tools_empty = resolve_tools([])
        tools_all = resolve_tools(["all"])
        assert set(id(t) for t in tools_empty) == set(id(t) for t in tools_all)
