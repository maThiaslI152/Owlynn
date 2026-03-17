import pytest
from unittest.mock import AsyncMock, patch
from langchain_core.messages import AIMessage, HumanMessage
from src.agent.graph import reason_node, validate_node
from src.agent.state import AgentState

@pytest.mark.asyncio
async def test_reason_node_async():
    # Mock LLM
    mock_llm = AsyncMock()
    # Mock a response with a tool call in text
    mock_llm.ainvoke.return_value = AIMessage(
        content='''<thought>I should list files.</thought>
```json
{
  "name": "list_workspace_files",
  "arguments": {"directory": "."}
}
```'''
    )
    
    # Create a state
    state: AgentState = {
        "messages": [HumanMessage(content="list files")],
        "mode": "reasoning",
        "current_task": None,
        "extracted_facts": [],
        "long_term_context": None,
        "execution_approved": None
    }
    
    # Mock get_llm to return our mock_llm
    with patch('src.agent.graph.get_llm', return_value=mock_llm):
        # Also mock get_persona, get_profile, memories_to_context to avoid crashes
        with patch('src.agent.graph.get_persona') as mock_persona, \
             patch('src.agent.graph.get_profile') as mock_profile, \
             patch('src.agent.graph.memories_to_context') as mock_mem:
            
            mock_persona.return_value = {}
            mock_profile.return_value = {}
            mock_mem.return_value = ""
            
            result = await reason_node(state)
        
    assert "messages" in result
    ans = result["messages"][0]
    assert hasattr(ans, "tool_calls")
    assert len(ans.tool_calls) == 1
    assert ans.tool_calls[0]["name"] == "list_workspace_files"

def test_validate_node():
    # Test safe command
    safe_message = AIMessage(content="Executing", tool_calls=[{
        "name": "execute_sandboxed_shell",
        "args": {"command": "ls -l"},
        "id": "call_1"
    }])
    state: AgentState = {"messages": [safe_message]}
    result = validate_node(state)
    assert result["execution_approved"] is True

    # Test dangerous command
    danger_message = AIMessage(content="Executing", tool_calls=[{
        "name": "execute_sandboxed_shell",
        "args": {"command": "rm -rf /"},
        "id": "call_2"
    }])
    state_danger: AgentState = {"messages": [danger_message]}
    result_danger = validate_node(state_danger)
    assert result_danger["execution_approved"] is False
    assert "messages" in result_danger
    assert "Security Exception" in result_danger["messages"][0].content
