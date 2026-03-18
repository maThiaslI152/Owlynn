import sys
from unittest.mock import AsyncMock, patch, MagicMock

# Mock mem0 BEFORE importing src to avoid Chroma connection on module load
sys.modules['mem0'] = MagicMock()

import pytest

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from src.agent.graph import build_graph, small_llm_node, simple_response_node, large_llm_node
from src.agent.state import AgentState

@pytest.mark.anyio
async def test_small_llm_node_simple():
    # Mock Small LLM to return SIMPLE
    mock_llm = AsyncMock()
    mock_llm.ainvoke.return_value = AIMessage(content='{"routing": "SIMPLE", "reason": "Just greeting"}')
    
    state: AgentState = {
        "messages": [HumanMessage(content="Hello")],
        "routing_decision": None,
        "current_task": None
    }
    
    with patch('src.agent.graph.get_small_llm', return_value=mock_llm):
        result = await small_llm_node(state)
        
    assert result["routing_decision"] == "SIMPLE"

@pytest.mark.anyio
async def test_small_llm_node_tool():
    # Mock Small LLM to return TOOL
    mock_llm = AsyncMock()
    mock_llm.ainvoke.return_value = AIMessage(content='{"routing": "TOOL", "reason": "Need list", "tool_name": "list_files", "tool_args": {"dir": "."}}')
    
    state: AgentState = {
        "messages": [HumanMessage(content="list files")],
        "routing_decision": None,
        "current_task": None
    }
    
    with patch('src.agent.graph.get_small_llm', return_value=mock_llm):
        result = await small_llm_node(state)
        
    assert result["routing_decision"] == "TOOL"
    assert "messages" in result
    assert hasattr(result["messages"][0], "tool_calls")
    assert result["messages"][0].tool_calls[0]["name"] == "list_files"

def test_graph_compilation():
    # Verify the graph compiles without errors
    try:
        graph = build_graph([])
        assert graph is not None
        # Try to compile with a checkpointer mock if needed, or just build_graph
        compiled = graph.compile()
        assert compiled is not None
    except Exception as e:
        pytest.fail(f"Graph compilation failed: {e}")
