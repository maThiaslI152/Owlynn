from langchain_core.messages import SystemMessage, AIMessage
from src.agent.state import AgentState
from src.agent.llm import get_small_llm
from src.agent.response_styles import style_instruction_for_prompt
from src.agent.lm_studio_compat import with_system_for_local_server

SIMPLE_PROMPT = """You are a concise, helpful assistant. Answer the user's question directly and briefly. Do not use tools. Do not over-explain.
Memory context (use only if relevant):
{memory_context}{style_hint}"""

async def simple_node(state: AgentState) -> AgentState:
    memory_context = state.get("memory_context", "None")
    style_hint = style_instruction_for_prompt(state.get("response_style"))
    small_llm = await get_small_llm()
    system = SystemMessage(
        content=SIMPLE_PROMPT.format(
            memory_context=memory_context,
            style_hint=style_hint,
        )
    )
    prompt_messages = with_system_for_local_server(system, list(state["messages"]))
    response = await small_llm.ainvoke(prompt_messages)
    return {
        "messages": [AIMessage(content=response.content)],
        "model_used": "small"
    }
