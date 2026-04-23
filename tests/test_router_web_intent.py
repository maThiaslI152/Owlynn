"""Router sends live-data questions to complex when web search is enabled."""

import sys
from unittest.mock import MagicMock

sys.modules["mem0"] = MagicMock()

import pytest
from langchain_core.messages import HumanMessage, AIMessage, ToolMessage

from src.agent.nodes.router import router_node
from src.agent.state import AgentState


@pytest.mark.anyio
async def test_weather_routes_complex_when_web_search_on():
    state: AgentState = {
        "messages": [HumanMessage(content="What's the weather in Tokyo right now?")],
        "web_search_enabled": True,
    }
    out = await router_node(state)
    assert out["route"].startswith("complex")
    assert "selected_toolboxes" in out


@pytest.mark.anyio
async def test_greeting_still_simple_with_web_on():
    state: AgentState = {
        "messages": [HumanMessage(content="Hi there!")],
        "web_search_enabled": True,
    }
    out = await router_node(state)
    assert out["route"] == "simple"


@pytest.mark.anyio
async def test_workspace_attachment_forces_complex():
    """Upload injections must not take the tool-less simple path."""
    state: AgentState = {
        "messages": [
            HumanMessage(
                content=(
                    "[Workspace file `notes.pdf` — text extracted from PDF below. "
                    "Use this to answer when it is enough; if not, call read_workspace_file …]\n\n---\nhello\n---\n\n"
                    "Summarize this."
                )
            )
        ],
        "web_search_enabled": True,
    }
    out = await router_node(state)
    assert out["route"].startswith("complex")


# ── Toolbox selection tests ──────────────────────────────────────────────

@pytest.mark.anyio
async def test_web_query_includes_web_search_toolbox():
    """Web-related queries should include web_search in selected_toolboxes."""
    state: AgentState = {
        "messages": [HumanMessage(content="Search the web for Python tutorials")],
        "web_search_enabled": True,
    }
    out = await router_node(state)
    assert out["route"].startswith("complex")
    assert "web_search" in out.get("selected_toolboxes", [])


@pytest.mark.anyio
async def test_selected_toolboxes_always_present():
    """Every routing result should include selected_toolboxes."""
    state: AgentState = {
        "messages": [HumanMessage(content="Hello!")],
        "web_search_enabled": True,
    }
    out = await router_node(state)
    assert "selected_toolboxes" in out
    assert isinstance(out["selected_toolboxes"], list)


# ── Vision detection tests ───────────────────────────────────────────────

@pytest.mark.anyio
async def test_image_attachment_routes_to_vision():
    """Image attachments should route to complex-vision."""
    from unittest.mock import patch, AsyncMock

    state: AgentState = {
        "messages": [
            HumanMessage(
                content=[
                    {"type": "text", "text": "Describe all objects visible in the uploaded image"},
                    {"type": "image_url", "image_url": {"url": "data:image/png;base64,abc123"}},
                ]
            )
        ],
        "web_search_enabled": True,
    }
    # Mock the small LLM to classify as complex
    mock_llm = MagicMock()
    mock_llm.bind.return_value = mock_llm
    mock_llm.ainvoke = AsyncMock(return_value=MagicMock(
        content='{"routing":"complex","confidence":0.9,"toolbox":"all"}'
    ))
    with patch("src.agent.nodes.router.get_small_llm", new_callable=AsyncMock, return_value=mock_llm):
        out = await router_node(state)
    assert out["route"] == "complex-vision"


# ── Cloud escalation tests ──────────────────────────────────────────────

@pytest.mark.anyio
async def test_frontier_quality_request_routes_cloud():
    """Frontier-quality indicators should route to complex-cloud when available."""
    from unittest.mock import patch, AsyncMock

    state: AgentState = {
        "messages": [HumanMessage(content="Solve and prove the convergence of a complex differential equation")],
        "web_search_enabled": True,
    }
    # Mock the small LLM to classify as complex
    mock_llm = MagicMock()
    mock_llm.bind.return_value = mock_llm
    mock_llm.ainvoke = AsyncMock(return_value=MagicMock(
        content='{"routing":"complex","confidence":0.9,"toolbox":"all"}'
    ))
    with patch("src.agent.nodes.router.get_small_llm", new_callable=AsyncMock, return_value=mock_llm), \
         patch("src.agent.nodes.router._check_cloud_available", return_value=True):
        out = await router_node(state)
    assert out["route"] == "complex-cloud"


@pytest.mark.anyio
async def test_tool_history_forces_complex_even_when_classifier_says_simple():
    """Tool-heavy conversations should not drift back to simple route."""
    state: AgentState = {
        "messages": [
            HumanMessage(content="read my workspace file and summarize"),
            AIMessage(content="", tool_calls=[{"name": "read_workspace_file", "args": {"filename": "notes.md"}, "id": "call_1"}]),
            ToolMessage(content="file contents...", tool_call_id="call_1", name="read_workspace_file"),
            HumanMessage(content="continue and finish this"),
        ],
        "web_search_enabled": True,
    }
    out = await router_node(state)
    assert out["route"].startswith("complex")


@pytest.mark.anyio
async def test_long_context_boundary_routes_longctx_not_default():
    """Prompt right above 80% default-context threshold should route to longctx/cloud."""
    long_text = "x" * 304_005  # just above longctx boundary for current heuristic
    state: AgentState = {
        "messages": [HumanMessage(content=long_text)],
        "web_search_enabled": True,
    }
    from unittest.mock import patch, AsyncMock

    mock_llm = MagicMock()
    mock_llm.bind.return_value = mock_llm
    mock_llm.ainvoke = AsyncMock(return_value=MagicMock(
        content='{"routing":"complex","confidence":0.95,"toolbox":"all"}'
    ))
    with patch("src.agent.nodes.router.get_small_llm", new_callable=AsyncMock, return_value=mock_llm):
        out = await router_node(state)
    assert out["route"] in ("complex-longctx", "complex-cloud")
