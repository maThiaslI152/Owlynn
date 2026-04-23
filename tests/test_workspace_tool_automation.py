"""
Automation tests for workspace tools (no live LLM by default).

Covers ``read_workspace_file`` (sync + async invoke) under the real project workspace
context. ``ToolNode`` itself requires a LangGraph runtime when used standalone, so we
validate the same tool the graph runs.

Optional live LLM check: RUN_LLM_INTEGRATION=1 pytest tests/test_workspace_tool_automation.py -m llm -q
"""

from __future__ import annotations

import os
import sys
from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.messages import AIMessage, HumanMessage

sys.modules["mem0"] = MagicMock()


from src.config.settings import get_project_workspace  # noqa: E402
from src.tools.core_tools import read_workspace_file  # noqa: E402
from src.tools.workspace_context import reset_active_project, set_active_project_for_run  # noqa: E402

PROBE_NAME = "_owlynn_automation_workspace_probe_.txt"
PROBE_TEXT = "Owlynn workspace tool probe — OK\nLine 2 for integration test.\n"


@pytest.fixture
def workspace_probe_file():
    """Create a file under projects/default with active project context set."""
    tok = set_active_project_for_run("default")
    root = get_project_workspace("default")
    path = os.path.join(root, PROBE_NAME)
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(PROBE_TEXT)
        yield path, PROBE_NAME
    finally:
        reset_active_project(tok)
        try:
            os.remove(path)
        except OSError:
            pass


def test_read_workspace_file_invokes_with_project_context(workspace_probe_file):
    _root, rel = workspace_probe_file
    tok = set_active_project_for_run("default")
    try:
        out = read_workspace_file.invoke({"filename": rel})
        assert "Owlynn workspace tool probe" in out
        assert "Line 2" in out
    finally:
        reset_active_project(tok)


@pytest.mark.anyio
async def test_read_workspace_file_ainvoke_async_path(workspace_probe_file):
    """Same as sync test but via BaseTool.ainvoke (matches LangChain tool execution)."""
    _root, rel = workspace_probe_file
    tok = set_active_project_for_run("default")
    try:
        out = await read_workspace_file.ainvoke({"filename": rel})
        assert "Owlynn workspace tool probe" in str(out)
    finally:
        reset_active_project(tok)


@pytest.mark.llm
@pytest.mark.anyio
async def test_live_llm_can_bind_and_call_read_workspace(monkeypatch, workspace_probe_file):
    """
    Calls the configured **large** LLM once with tools bound; expects a read_workspace_file tool call.
    Requires a reachable OpenAI-compatible server (see profile / env). Disabled unless RUN_LLM_INTEGRATION=1.
    """
    if os.getenv("RUN_LLM_INTEGRATION") != "1":
        pytest.skip("Set RUN_LLM_INTEGRATION=1 and start your local LLM server.")

    from src.agent.llm import get_large_llm
    from src.agent.tool_sets import COMPLEX_TOOLS_NO_WEB
    from src.agent.lm_studio_compat import with_system_for_local_server
    from langchain_core.messages import SystemMessage

    _root, rel = workspace_probe_file
    tok = set_active_project_for_run("default")
    try:
        system = SystemMessage(
            content=(
                "You are a test assistant. The user needs file contents. "
                "You MUST call the read_workspace_file tool exactly once with the filename they give. "
                "Do not answer with prose only."
            )
        )
        thread = [HumanMessage(content=f"Read the file named exactly: {rel}")]
        prompt = with_system_for_local_server(system, thread)
        large = await get_large_llm()
        bound = large.bind_tools(COMPLEX_TOOLS_NO_WEB)
        response = await bound.ainvoke(prompt)
        tcalls = getattr(response, "tool_calls", None) or []
        assert tcalls, "Model should emit tool_calls for read_workspace_file; check local server tool support."
        names = {str(tc.get("name", "")) for tc in tcalls}
        assert "read_workspace_file" in names
    finally:
        reset_active_project(tok)
