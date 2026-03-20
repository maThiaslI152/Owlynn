from langchain_core.messages import SystemMessage, AIMessage
from langgraph.prebuilt import ToolNode

from src.agent.state import AgentState
from src.agent.llm import get_large_llm
from src.agent.response_styles import style_instruction_for_prompt
from src.agent.tool_sets import COMPLEX_TOOLS_NO_WEB, COMPLEX_TOOLS_WITH_WEB
from src.agent.lm_studio_compat import with_system_for_local_server

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
- Never fabricate facts — if uncertain, say so{style_hint}"""

COMPLEX_TOOL_GUIDANCE_WEB = """
You can call tools when they help answer the user accurately:
- web_search: Use for current prices, retailer sites, product availability, news, or anything that needs up-to-date web information. If the user asks you to look something up, search, or verify online — call web_search instead of claiming you cannot browse.
- read_workspace_file: Read a file from the user's workspace when relevant.
- execute_python_code: Run calculations or short scripts in the sandbox when needed.
- recall_memories: Search stored long-term memories about the user.

After tools return, summarize results clearly for the user (include sources when from web_search)."""

COMPLEX_TOOL_GUIDANCE_NO_WEB = """
You can call tools when they help answer the user accurately (web search is turned off for this chat — do not call web_search; use workspace files, sandbox Python, and memory tools only):
- read_workspace_file: Read a file from the user's workspace when relevant.
- execute_python_code: Run calculations or short scripts in the sandbox when needed.
- recall_memories: Search stored long-term memories about the user.

After tools return, summarize results clearly for the user."""


async def complex_node(state: AgentState) -> AgentState:
    memory_context = state.get("memory_context", "None")
    persona = state.get("persona", "No persona available")
    mode = state.get("mode") or "tools_on"
    thread_messages = list(state.get("messages") or [])

    web_on = state.get("web_search_enabled")
    if web_on is None:
        web_on = True
    web_on = bool(web_on)

    style_hint = style_instruction_for_prompt(state.get("response_style"))

    system_text = COMPLEX_PROMPT.format(
        memory_context=memory_context,
        persona=persona,
        style_hint=style_hint,
    )
    if mode != "tools_off":
        system_text += COMPLEX_TOOL_GUIDANCE_WEB if web_on else COMPLEX_TOOL_GUIDANCE_NO_WEB

    system = SystemMessage(content=system_text)

    if mode == "tools_off":
        large_llm = await get_large_llm()
        prompt_messages = with_system_for_local_server(system, thread_messages)
        response = await large_llm.ainvoke(prompt_messages)
        return {
            "messages": [AIMessage(content=response.content)],
            "model_used": "large",
        }

    tools = COMPLEX_TOOLS_WITH_WEB if web_on else COMPLEX_TOOLS_NO_WEB
    tool_node = ToolNode(tools)

    large_base = await get_large_llm()
    large_llm = large_base.bind_tools(tools)

    prompt_messages = with_system_for_local_server(system, thread_messages)
    response = await large_llm.ainvoke(prompt_messages)

    if not (getattr(response, "tool_calls", None) and response.tool_calls):
        return {"messages": [response], "model_used": "large"}

    after_first = thread_messages + [response]
    tool_payload = await tool_node.ainvoke({"messages": after_first})
    messages_after_tools = tool_payload["messages"]
    final_response = await large_llm.ainvoke(messages_after_tools)

    delta = messages_after_tools[len(thread_messages) :] + [final_response]
    return {"messages": delta, "model_used": "large"}
