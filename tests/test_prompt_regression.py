import sys
from unittest.mock import AsyncMock, MagicMock, patch

# Mock mem0 before importing project modules that may load long-term memory.
sys.modules["mem0"] = MagicMock()

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from src.agent.graph import build_graph
from src.agent.nodes.memory import memory_inject_node
from src.agent.nodes.tool_executor import tool_executor_node
from src.agent.state import AgentState


SMALL_PROMPT = "Hi! Reply with exactly: SMALL_OK"
COMPLEX_PROMPT = (
    "Design a 3-phase migration plan from monolith to microservices for a 20-person "
    "engineering team, including risks, rollback strategy, and weekly milestones."
)
TOOL_PROMPT = (
    'Please search the web for "latest LangGraph release highlights" and summarize in 5 bullets.'
)


@pytest.mark.anyio
async def test_prompt_regression_small_route():
    """
    Verifies a small-path style prompt is answered through the simple node.
    """
    app = build_graph().compile()

    mock_simple_llm = AsyncMock()
    mock_simple_llm.ainvoke.return_value = AIMessage(content="SMALL_OK")

    with patch("src.agent.nodes.simple.get_small_llm", AsyncMock(return_value=mock_simple_llm)), \
         patch("src.agent.nodes.memory.get_profile", return_value={}), \
         patch("src.agent.nodes.memory.get_persona", return_value={"role": "assistant"}), \
         patch("src.agent.nodes.memory.get_memory_context_for_prompt", return_value=""), \
         patch("src.agent.nodes.memory.record_conversation", return_value=None), \
         patch("src.memory.long_term.memory", None):
        state: AgentState = {
            "messages": [HumanMessage(content=SMALL_PROMPT)],
            "thread_id": "prompt-reg-small",
        }
        result = await app.ainvoke(
            state,
            config={"configurable": {"thread_id": "prompt-reg-small"}},
        )

    assert result["route"] == "simple"
    assert result["model_used"] == "small"
    assert result["messages"][-1].content == "SMALL_OK"


@pytest.mark.anyio
async def test_prompt_regression_complex_route():
    """
    Verifies a complex planning prompt routes to the large-model path.
    """
    app = build_graph().compile()

    mock_router_llm = AsyncMock()
    mock_router_llm.ainvoke.return_value = AIMessage(content='{"routing": "complex", "confidence": 0.99}')

    mock_bound = AsyncMock()
    mock_bound.ainvoke.return_value = AIMessage(
        content="Phase 1, Phase 2, Phase 3 with risks and rollback."
    )
    mock_large_base = MagicMock()
    mock_large_base.bind_tools = MagicMock(return_value=mock_bound)

    with patch("src.agent.nodes.router.get_small_llm", AsyncMock(return_value=mock_router_llm)), \
         patch("src.agent.nodes.complex.get_large_llm", AsyncMock(return_value=mock_large_base)), \
         patch("src.agent.nodes.memory.get_profile", return_value={}), \
         patch("src.agent.nodes.memory.get_persona", return_value={"role": "assistant"}), \
         patch("src.agent.nodes.memory.get_memory_context_for_prompt", return_value=""), \
         patch("src.agent.nodes.memory.record_conversation", return_value=None), \
         patch("src.memory.long_term.memory", None):
        state: AgentState = {
            "messages": [HumanMessage(content=COMPLEX_PROMPT)],
            "thread_id": "prompt-reg-complex",
        }
        result = await app.ainvoke(
            state,
            config={"configurable": {"thread_id": "prompt-reg-complex"}},
        )

    assert result["route"] == "complex"
    assert result["model_used"] == "large"
    assert "Phase 1" in result["messages"][-1].content


@pytest.mark.anyio
async def test_prompt_regression_memory_injection():
    """
    Verifies memory context returned by personal-assistant memory is injected.
    """
    marker = "preferred deploy region is ap-southeast-1"
    state: AgentState = {
        "messages": [HumanMessage(content="What deploy region do I prefer?")],
        "thread_id": "prompt-reg-memory",
    }

    with patch("src.agent.nodes.memory.get_profile", return_value={"name": "Tim"}), \
         patch("src.agent.nodes.memory.get_persona", return_value={"role": "helpful assistant"}), \
         patch("src.agent.nodes.memory.get_memory_context_for_prompt", return_value=marker), \
         patch("src.memory.long_term.memory", None):
        result = await memory_inject_node(state)

    assert "memory_context" in result
    assert marker in result["memory_context"]
    assert result["persona"] == "helpful assistant"


@pytest.mark.anyio
async def test_prompt_regression_tool_request():
    """
    Verifies tool-request flow: model emits tool call -> tool executes -> final answer produced.
    """
    first_response = AIMessage(
        content="",
        tool_calls=[
            {
                "name": "web_search",
                "args": {"query": "latest LangGraph release highlights"},
                "id": "call_tool_regression",
            }
        ],
    )
    final_response = AIMessage(content="Here are 5 highlights with sources.")

    mock_large_tools_llm = AsyncMock()
    mock_large_tools_llm.ainvoke.side_effect = [first_response, final_response]

    mock_tool_node = AsyncMock()
    mock_tool_node.ainvoke.return_value = {
        "messages": [
            HumanMessage(content=TOOL_PROMPT),
            first_response,
            ToolMessage(content="Result: release notes snippet", tool_call_id="call_tool_regression"),
        ]
    }

    state: AgentState = {
        "messages": [HumanMessage(content=TOOL_PROMPT)],
        "selected_tool": "web_search",
        "memory_context": "None",
    }

    with patch(
        "src.agent.nodes.tool_executor.get_large_llm_with_tools",
        AsyncMock(return_value=mock_large_tools_llm),
    ), patch("src.agent.nodes.tool_executor.tool_node", mock_tool_node):
        result = await tool_executor_node(state)

    assert result["model_used"] == "large"
    assert "tool_result" in result
    assert "release notes snippet" in result["tool_result"]
    assert result["messages"][-1].content == "Here are 5 highlights with sources."
