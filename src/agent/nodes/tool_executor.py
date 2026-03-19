from langchain_core.messages import SystemMessage, AIMessage
from src.agent.state import AgentState
from src.agent.llm import get_large_llm_with_tools
from langgraph.prebuilt import ToolNode
from src.tools import web_search, execute_python_code, read_workspace_file, recall_memories

# Define tools for ToolNode (must match to bound tools)
TOOLS = [web_search, execute_python_code, read_workspace_file, recall_memories]
tool_node = ToolNode(TOOLS)

EXECUTOR_PROMPT = """You are a reasoning agent. The tool to use has already been selected: {tool_name}.
Your job:
1. Generate the correct arguments for this tool based on the user's message.
2. Interpret the tool result and formulate a final response.

Memory context:
{memory_context}"""

async def tool_executor_node(state: AgentState) -> AgentState:
    large_llm_with_tools = await get_large_llm_with_tools()
    tool_name = state.get("selected_tool", "web_search")
    memory_context = state.get("memory_context", "None")
    
    prompt = EXECUTOR_PROMPT.format(
        tool_name=tool_name,
        memory_context=memory_context
    )
    
    messages = state.get("messages", [])

    # Large model generates tool args or responds
    response = await large_llm_with_tools.ainvoke([
        SystemMessage(content=prompt),
        *messages
    ])
    
    updated_messages = list(messages) + [response]
    result_val = None

    if response.tool_calls:
        # Execute tool via ToolNode
        tool_output = await tool_node.ainvoke({"messages": updated_messages})
        updated_messages = tool_output["messages"]
        
        # Capture raw result content for backward compatibility
        if updated_messages:
            result_val = updated_messages[-1].content
            
        # Call LLM again to interpret result and produce final response
        final_response = await large_llm_with_tools.ainvoke(updated_messages)
        updated_messages.append(final_response)
    else:
        result_val = "Model did not issue a tool call. Response: " + str(response.content)

    return {
        "messages": updated_messages,
        "tool_result": str(result_val) if result_val else None,
        "model_used": "large"
    }
