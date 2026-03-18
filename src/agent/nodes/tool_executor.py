from langchain_core.messages import SystemMessage, HumanMessage
from src.agent.state import AgentState
from src.agent.llm import large_llm
from src.tools import tool_registry

EXECUTOR_PROMPT = """You are a reasoning agent. The tool to use has already been selected: {tool_name}.
Your job:
1. Generate the correct arguments for this tool based on the user's message.
2. Interpret the tool result and formulate a final response.

Memory context:
{memory_context}"""

async def tool_executor_node(state: AgentState) -> AgentState:
    tool_name = state.get("selected_tool", "web_search")
    tool_fn = tool_registry.get(tool_name)
    
    memory_context = state.get("memory_context", "None")
    
    prompt = EXECUTOR_PROMPT.format(
        tool_name=tool_name,
        memory_context=memory_context
    )
    
    messages = state.get("messages", [])
    user_message = messages[-1].content if messages else ""

    # Large model generates tool args (or processes the prompt)
    arg_response = await large_llm.ainvoke([
        SystemMessage(content=prompt),
        HumanMessage(content=str(user_message))
    ])
    
    if tool_fn:
        try:
             tool_result = await tool_fn(arg_response.content)
             result_val = tool_result
        except Exception as e:
             result_val = f"Error executing tool '{tool_name}': {str(e)}"
    else:
        result_val = f"Tool '{tool_name}' not found in registry."
        
    return {
        "tool_result": result_val,
        "model_used": "large"
    }
