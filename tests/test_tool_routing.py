import sys
from unittest.mock import AsyncMock, patch, MagicMock

# Mock mem0 BEFORE importing src to avoid Chroma connection on module load
sys.modules['mem0'] = MagicMock()

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from src.agent.graph import build_graph
from src.agent.state import AgentState

@pytest.mark.anyio
async def test_tool_routing():
    """
    Test the full graph walkthrough for a 'tool' route request.
    Steps:
      1. memory_inject -> Sets up state
      2. router -> Sets route to 'tool'
      3. tool_selector -> Sets selected_tool to 'web_search'
      4. tool_executor -> Executes web_search
      5. memory_write -> Finalize
    """
    
    # 1. Compile the graph
    app = build_graph().compile()
    
    # 2. Setup Mocks for LLMs in respective node files
    mock_router_llm = AsyncMock()
    # Router returns "tool"
    mock_router_llm.ainvoke.return_value = AIMessage(content='{"routing": "tool", "reason": "Needs lookup"}')
    
    mock_selector_llm = AsyncMock()
    # Selector returns "web_search"
    mock_selector_llm.ainvoke.return_value = AIMessage(content="web_search")
    
    mock_executor_llm = AsyncMock()
    # Executor returns arg string
    mock_executor_llm.ainvoke.return_value = AIMessage(content="weather in Bangkok")
    
    # Mock tool registry or function
    mock_web_search = AsyncMock(return_value="Sunny, 32°C in Bangkok")
    
    # 3. Patching everything into the path
    with patch('src.agent.nodes.router.small_llm', mock_router_llm), \
         patch('src.agent.nodes.tool_selector.small_llm', mock_selector_llm), \
         patch('src.agent.nodes.tool_executor.large_llm', mock_executor_llm), \
         patch('src.agent.nodes.tool_executor.tool_registry', {"web_search": mock_web_search}):
         
         initial_state: AgentState = {
             "messages": [HumanMessage(content="What is the weather in Bangkok today?")],
             "thread_id": "test-001"
         }
         
         result = await app.ainvoke(
             initial_state,
             config={"configurable": {"thread_id": "test-001"}}
         )

    # 4. Assertions
    assert result["route"] == "tool"
    assert result["selected_tool"] == "web_search"
    assert result["tool_result"] == "Sunny, 32°C in Bangkok"
    
@pytest.mark.anyio
async def test_simple_routing():
    """Test simple path."""
    app = build_graph().compile()
    
    mock_router_llm = AsyncMock()
    mock_router_llm.ainvoke.return_value = AIMessage(content='{"routing": "simple"}')
    
    mock_simple_llm = AsyncMock()
    mock_simple_llm.ainvoke.return_value = AIMessage(content="Hello! I am fine.")

    with patch('src.agent.nodes.router.small_llm', mock_router_llm), \
         patch('src.agent.nodes.simple.small_llm', mock_simple_llm):
         
         initial_state: AgentState = {
             "messages": [HumanMessage(content="Hello")],
             "thread_id": "test-001"
         }
         
         result = await app.ainvoke(
             initial_state,
             config={"configurable": {"thread_id": "test-001"}}
         )
         
    assert result["route"] == "simple"
    # AIMessage appended
    assert len(result["messages"]) == 2
    assert result["messages"][-1].content == "Hello! I am fine."
