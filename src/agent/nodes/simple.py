from langchain_core.messages import SystemMessage, HumanMessage, AIMessage
from src.agent.state import AgentState
from src.agent.llm import small_llm

SIMPLE_PROMPT = """You are a concise, helpful assistant. Answer the user's question directly and briefly. Do not use tools. Do not over-explain.
Memory context (use only if relevant):
{memory_context}"""

async def simple_node(state: AgentState) -> AgentState:
    memory_context = state.get("memory_context", "None")
    response = await small_llm.ainvoke([
        SystemMessage(content=SIMPLE_PROMPT.format(
            memory_context=memory_context
        )),
        *state["messages"]   # pass full thread for coherence
    ])
    return {
        "messages": [AIMessage(content=response.content)],
        "model_used": "small"
    }
