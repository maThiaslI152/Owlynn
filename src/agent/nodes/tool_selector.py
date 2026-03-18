from langchain_core.messages import SystemMessage, HumanMessage
from src.agent.state import AgentState
from src.agent.llm import small_llm

AVAILABLE_TOOLS = ["web_search", "sandbox", "file_read", "memory_search"]

TOOL_SELECTOR_PROMPT = f"""You are a tool dispatcher. Given a user message, output ONLY the name of the most appropriate tool to use. No explanation, no punctuation — just the tool name.

Available tools:
- web_search   : search the internet for current information
- sandbox      : execute Python code or shell commands
- file_read    : read a local file
- memory_search: search the user's long-term memory

Reply with exactly one of: {", ".join(AVAILABLE_TOOLS)}"""

def parse_tool(raw: str) -> str:
    if not raw:
        return "web_search"
    cleaned = raw.strip().lower().split()[0].rstrip(".,;:")
    return cleaned if cleaned in AVAILABLE_TOOLS else "web_search"  # safe default

async def tool_selector_node(state: AgentState) -> AgentState:
    messages = state.get("messages", [])
    user_message = messages[-1].content if messages else ""
    
    response = await small_llm.ainvoke([
        SystemMessage(content=TOOL_SELECTOR_PROMPT),
        HumanMessage(content=str(user_message))
    ])
    
    selected = parse_tool(response.content)
    print(f"[tool_selector] → {selected}")
    return {
        "selected_tool": selected,
        "model_used": "small"
    }
