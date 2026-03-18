import sys
from unittest.mock import AsyncMock, patch, MagicMock

# Mock mem0 and other heavy imports if needed
sys.modules['mem0'] = MagicMock()

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from src.agent.state import AgentState

# Import the node to test
from src.agent.nodes.tool_executor import tool_executor_node

@pytest.mark.anyio
async def test_tool_executor_node_with_tool_call():
    # 1. Setup Mock for large_llm_with_tools
    mock_llm = AsyncMock()
    
    # First call: returns a ToolCall
    first_response = AIMessage(
        content="",
        tool_calls=[{
            "name": "web_search",
            "args": {"query": "test query"},
            "id": "call_123"
        }]
    )
    # Second call (interpretation): returns final text
    second_response = AIMessage(content="I searched and found results.")
    
    mock_llm.ainvoke.side_effect = [first_response, second_response]

    # 2. Setup Mock for ToolNode
    mock_tool_output = {
        "messages": [
            first_response, 
            ToolMessage(content="SearchResult: found 42", tool_call_id="call_123")
        ]
    }
    mock_tool_node = AsyncMock()
    mock_tool_node.ainvoke.return_value = mock_tool_output

    # 3. Define State
    state: AgentState = {
        "messages": [HumanMessage(content="Search for X")],
        "selected_tool": "web_search",
        "memory_context": "None"
    }

    # 4. Patch dependencies
    with patch('src.agent.nodes.tool_executor.large_llm_with_tools', mock_llm), \
         patch('src.agent.nodes.tool_executor.tool_node', mock_tool_node):
         
        result = await tool_executor_node(state)

    # 5. Assertions
    # Check updated messages: Human -> AIMessage (tool) -> ToolMessage -> AIMessage (text)
    messages = result["messages"]
    assert len(messages) == 4
    assert isinstance(messages[1], AIMessage)
    assert messages[1].tool_calls
    assert isinstance(messages[2], ToolMessage)
    assert isinstance(messages[3], AIMessage)
    assert messages[3].content == "I searched and found results."
    
    # Check tool_result is set for compatibility
    assert result["tool_result"] == "SearchResult: found 42"
    assert result["model_used"] == "large"

@pytest.mark.anyio
async def test_tool_executor_node_no_tool_call():
    # Setup Mock: returns text response directly
    mock_llm = AsyncMock()
    mock_llm.ainvoke.return_value = AIMessage(content="I can answer that directly.")

    state: AgentState = {
        "messages": [HumanMessage(content="Hello")],
        "selected_tool": "web_search"
    }

    with patch('src.agent.nodes.tool_executor.large_llm_with_tools', mock_llm):
        result = await tool_executor_node(state)

    messages = result["messages"]
    assert len(messages) == 2
    assert isinstance(messages[1], AIMessage)
    assert "Directly" in messages[1].content
    assert "did not issue a tool call" in result["tool_result"]
