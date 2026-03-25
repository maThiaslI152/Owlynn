import sys
from unittest.mock import AsyncMock, MagicMock, patch

# Prevent mem0/chroma bootstrapping during tests.
sys.modules["mem0"] = MagicMock()

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from src.agent.graph import build_graph
from src.agent.state import AgentState


SIMPLE_CASES = [
    ("Hi there", "simple", "small", "SMALL: greeting"),
    ("Hello, how are you?", "simple", "small", "SMALL: greeting"),
    ("Thanks for your help!", "simple", "small", "SMALL: greeting"),
]

COMPLEX_CASES = [
    (
        "Design a migration strategy from monolith to microservices with rollout phases.",
        "complex",
        "large",
        "LARGE: architecture plan",
    ),
    (
        "Write and explain a Python quicksort implementation with complexity analysis.",
        "complex",
        "large",
        "LARGE: architecture plan",
    ),
]


@pytest.mark.anyio
@pytest.mark.parametrize("sentence,expected_route,expected_model,expected_reply", SIMPLE_CASES)
async def test_sentence_matrix_simple_route_and_response(
    sentence: str, expected_route: str, expected_model: str, expected_reply: str
):
    app = build_graph().compile()

    mock_simple_llm = AsyncMock()
    mock_simple_llm.bind = MagicMock(return_value=mock_simple_llm)
    mock_simple_llm.ainvoke.return_value = AIMessage(content=expected_reply)

    with patch("src.agent.nodes.simple.get_small_llm", AsyncMock(return_value=mock_simple_llm)), \
         patch("src.agent.nodes.memory.get_profile", return_value={}), \
         patch("src.agent.nodes.memory.get_persona", return_value={"role": "assistant"}), \
         patch("src.agent.nodes.memory.get_memory_context_for_prompt", return_value=""), \
         patch("src.agent.nodes.memory.record_conversation", return_value=None), \
         patch("src.memory.long_term.memory", None):
        state: AgentState = {"messages": [HumanMessage(content=sentence)], "thread_id": "route-simple"}
        result = await app.ainvoke(
            state,
            config={"configurable": {"thread_id": "route-simple"}},
        )

    assert result["route"] == expected_route
    assert result["model_used"] == expected_model
    assert result["messages"][-1].content == expected_reply


@pytest.mark.anyio
@pytest.mark.parametrize("sentence,expected_route,expected_model,expected_reply", COMPLEX_CASES)
async def test_sentence_matrix_complex_route_and_response(
    sentence: str, expected_route: str, expected_model: str, expected_reply: str
):
    app = build_graph().compile()

    # Force router classification for non-keyword complex prompts.
    mock_router_llm = AsyncMock()
    mock_router_llm.bind = MagicMock(return_value=mock_router_llm)
    mock_router_llm.ainvoke.return_value = AIMessage(content='{"routing":"complex","confidence":0.98}')

    mock_bound = AsyncMock()
    mock_bound.ainvoke.return_value = AIMessage(content=expected_reply)
    mock_large_base = MagicMock()
    mock_large_base.bind_tools = MagicMock(return_value=mock_bound)

    with patch("src.agent.nodes.router.get_small_llm", AsyncMock(return_value=mock_router_llm)), \
         patch("src.agent.nodes.complex.get_large_llm", AsyncMock(return_value=mock_large_base)), \
         patch("src.agent.nodes.memory.get_profile", return_value={}), \
         patch("src.agent.nodes.memory.get_persona", return_value={"role": "assistant"}), \
         patch("src.agent.nodes.memory.get_memory_context_for_prompt", return_value=""), \
         patch("src.agent.nodes.memory.record_conversation", return_value=None), \
         patch("src.memory.long_term.memory", None):
        state: AgentState = {"messages": [HumanMessage(content=sentence)], "thread_id": "route-complex"}
        result = await app.ainvoke(
            state,
            config={"configurable": {"thread_id": "route-complex"}},
        )

    assert result["route"] == expected_route
    assert result["model_used"] == expected_model
    assert result["messages"][-1].content == expected_reply
