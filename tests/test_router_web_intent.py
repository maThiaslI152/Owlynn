"""Router sends live-data questions to complex when web search is enabled."""

import sys
from unittest.mock import MagicMock

sys.modules["mem0"] = MagicMock()

import pytest
from langchain_core.messages import HumanMessage

from src.agent.nodes.router import router_node
from src.agent.state import AgentState


@pytest.mark.anyio
async def test_weather_routes_complex_when_web_search_on():
    state: AgentState = {
        "messages": [HumanMessage(content="What's the weather in Tokyo right now?")],
        "web_search_enabled": True,
    }
    out = await router_node(state)
    assert out["route"] == "complex"


@pytest.mark.anyio
async def test_greeting_still_simple_with_web_on():
    state: AgentState = {
        "messages": [HumanMessage(content="Hi there!")],
        "web_search_enabled": True,
    }
    out = await router_node(state)
    assert out["route"] == "simple"
