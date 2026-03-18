from langchain_core.messages import SystemMessage, HumanMessage, AIMessage
from src.agent.state import AgentState
from src.agent.llm import large_llm

COMPLEX_PROMPT = """You are an expert reasoning agent. Think step by step before answering.
You have access to the user's memory context below — use it to personalize and ground your response.

User memory context:
{memory_context}

User persona summary:
{persona}

Guidelines:
- Be thorough and accurate
- If writing code, include comments
- If reasoning through a problem, show your thinking clearly
- Never fabricate facts — if uncertain, say so"""

async def complex_node(state: AgentState) -> AgentState:
    memory_context = state.get("memory_context", "None")
    persona        = state.get("persona", "No persona available")
    response = await large_llm.ainvoke([
        SystemMessage(content=COMPLEX_PROMPT.format(
            memory_context=memory_context,
            persona=persona,
        )),
        *state["messages"]
    ])
    return {
        "messages": [AIMessage(content=response.content)],
        "model_used": "large"
    }
