from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
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
You can call tools when they help answer the user accurately. For web questions, use a frontier-style workflow:

1) web_search: Find candidate pages. Pass focus_query with the user's precise information need when it differs from the search keywords — results will be reranked for relevance.
2) fetch_webpage: Open URLs **exactly as listed** under each search hit (do not invent URLs from titles — e.g. do not assume ``deepseek.ai`` paths for third-party articles). Always pass focus_query so long pages return ranked excerpts with [1], [2], … for citation. If static fetch returns almost no text or says to use dynamic fetch, call **fetch_webpage_dynamic** on the same URL or switch to another hit from web_search.
3) read_workspace_file: Read a file from the user's workspace when relevant.
4) execute_python_code: Run calculations or short scripts in the sandbox (non-interactive: never use input(); use fixed args or literals).
5) recall_memories: Search stored long-term memories about the user.

Answer rules after tools return:
- Ground claims in tool output only; do not invent facts, URLs, or quotes.
- Use numbered citations [1], [2] in the answer that match excerpt numbers from fetch_webpage when you used them; include the source URL at least once per citation family.
- If sources disagree, say so briefly. If tools returned nothing useful, say you could not verify online and avoid fabricating."""

COMPLEX_TOOL_GUIDANCE_NO_WEB = """
You can call tools when they help answer the user accurately (web search is turned off for this chat — do not call web_search; use workspace files, sandbox Python, and memory tools only):
- read_workspace_file: Read a file from the user's workspace when relevant.
- execute_python_code: Run calculations or short scripts in the sandbox (non-interactive: never use input(); use fixed args or literals).
- recall_memories: Search stored long-term memories about the user.

After tools return, summarize results clearly for the user."""


def build_fetch_retry_nudge_messages(tool_messages: list) -> list[HumanMessage]:
    """
    If fetch_webpage clearly failed or only returned SPA metadata, append a one-shot user-role
    reminder so the next LLM turn retries fetch_webpage_dynamic or another search hit.
    """
    if not tool_messages:
        return []
    need_dynamic = False
    need_alt_url = False
    for m in tool_messages:
        if not isinstance(m, ToolMessage):
            continue
        if (getattr(m, "name", None) or "") != "fetch_webpage":
            continue
        c = m.content if isinstance(m.content, str) else str(m.content or "")
        if (
            "[fetch_webpage] No extractable text" in c
            or "[Note: Page body is mostly empty in static HTML" in c
        ):
            need_dynamic = True
        if c.startswith("[fetch_webpage] HTTP error"):
            need_alt_url = True
    out: list[HumanMessage] = []
    if need_dynamic:
        out.append(
            HumanMessage(
                content=(
                    "[Internal reminder for assistant] Static **fetch_webpage** returned no usable article body "
                    "(empty HTML or SPA shell). Before answering the user, call **fetch_webpage_dynamic** with the "
                    "same URL, or **fetch_webpage** a different URL from **web_search** results."
                )
            )
        )
    elif need_alt_url:
        out.append(
            HumanMessage(
                content=(
                    "[Internal reminder for assistant] **fetch_webpage** failed with an HTTP error. "
                    "Open another result from **web_search** instead of repeating the same URL."
                )
            )
        )
    return out


def _fallback_for_blank_response(messages: list, *, web_search_enabled: bool) -> AIMessage:
    """
    When the model returns empty assistant content, synthesize a safe user-visible reply.

    Prefers context from recent ``ToolMessage`` outputs (e.g. failed web_search). If there are no
    tool messages yet (first LLM turn before any tools) or no matching failure, returns a generic
    message so the thread does not stay blank.
    """
    for m in reversed(messages):
        if not isinstance(m, ToolMessage):
            continue
        c = m.content if isinstance(m.content, str) else str(m.content or "")
        if (getattr(m, "name", None) or "") == "web_search" and (
            c.startswith("[web_search]")
            or "Unable to retrieve online results" in c
            or "blocked_by_captcha" in c
        ):
            return AIMessage(
                content=(
                    "I couldn’t verify this online right now because web search providers returned "
                    "errors or bot challenges. I did not find reliable live sources in this run. "
                    "If you want, I can retry with a narrower query, a different provider, or use "
                    "another source you provide."
                )
            )
    if web_search_enabled:
        return AIMessage(
            content=(
                "I didn’t get a usable reply from the model this time (empty response). "
                "Try rephrasing or shortening your message, confirm your LLM server is running, "
                "or retry. If you need live web facts, we can try again once the model responds normally."
            )
        )
    return AIMessage(
        content=(
            "I didn’t get a usable reply from the model this time (empty response). "
            "Try rephrasing your question or confirm your local LLM is running correctly, then retry."
        )
    )


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
    messages_after_tools = list(tool_payload["messages"])
    tool_only = messages_after_tools[len(after_first) :]
    nudge = build_fetch_retry_nudge_messages(tool_only) if web_on else []
    if nudge:
        messages_after_tools = messages_after_tools + nudge
    final_response = await large_llm.ainvoke(messages_after_tools)
    if not str(getattr(final_response, "content", "") or "").strip():
        final_response = _fallback_for_blank_response(
            messages_after_tools, web_search_enabled=web_on
        )

    delta = messages_after_tools[len(thread_messages) :] + [final_response]
    return {"messages": delta, "model_used": "large"}


async def complex_llm_node(state: AgentState) -> AgentState:
    """
    LLM reasoning node for the cyclic secure tool flow.
    It either answers directly or emits tool calls for the security proxy.
    """
    memory_context = state.get("memory_context", "None")
    persona = state.get("persona", "No persona available")
    mode = state.get("mode") or "tools_on"
    thread_messages = list(state.get("messages") or [])

    web_on = state.get("web_search_enabled")
    if web_on is None:
        web_on = True
    web_on = bool(web_on)

    style_hint = style_instruction_for_prompt(state.get("response_style"))
    security_decision = state.get("security_decision")
    security_reason = state.get("security_reason")

    system_text = COMPLEX_PROMPT.format(
        memory_context=memory_context,
        persona=persona,
        style_hint=style_hint,
    )
    if mode != "tools_off":
        system_text += COMPLEX_TOOL_GUIDANCE_WEB if web_on else COMPLEX_TOOL_GUIDANCE_NO_WEB

    if security_decision == "denied":
        system_text += (
            "\n\nSecurity notice: A previous tool request was denied by policy or user approval. "
            "Do not retry blocked operations. Provide a safe alternative response instead."
        )
        if security_reason:
            system_text += f"\nBlocked reason: {security_reason}"

    system = SystemMessage(content=system_text)
    prompt_messages = with_system_for_local_server(system, thread_messages)

    if mode == "tools_off":
        large_llm = await get_large_llm()
        response = await large_llm.ainvoke(prompt_messages)
        return {
            "messages": [AIMessage(content=response.content)],
            "model_used": "large",
            "pending_tool_calls": False,
        }

    tools = COMPLEX_TOOLS_WITH_WEB if web_on else COMPLEX_TOOLS_NO_WEB
    large_llm = (await get_large_llm()).bind_tools(tools)
    response = await large_llm.ainvoke(prompt_messages)
    has_tool_calls = bool(getattr(response, "tool_calls", None))
    if not has_tool_calls and not str(getattr(response, "content", "") or "").strip():
        response = _fallback_for_blank_response(
            thread_messages, web_search_enabled=web_on
        )

    return {
        "messages": [response],
        "model_used": "large",
        "pending_tool_calls": bool(getattr(response, "tool_calls", None)),
        # Clear prior deny state after a fresh LLM turn.
        "security_decision": None,
        "security_reason": None,
    }


async def complex_tool_action_node(state: AgentState) -> AgentState:
    """
    Executes already-approved tool calls and appends tool outputs to the thread.
    """
    current_messages = list(state.get("messages") or [])
    if not current_messages:
        return {"pending_tool_calls": False}

    last_message = current_messages[-1]
    if not bool(getattr(last_message, "tool_calls", None)):
        return {"pending_tool_calls": False}

    web_on = state.get("web_search_enabled")
    if web_on is None:
        web_on = True
    web_on = bool(web_on)

    tools = COMPLEX_TOOLS_WITH_WEB if web_on else COMPLEX_TOOLS_NO_WEB
    tool_node = ToolNode(tools)
    tool_payload = await tool_node.ainvoke({"messages": current_messages})
    output_messages = tool_payload.get("messages", [])

    if len(output_messages) >= len(current_messages):
        delta = output_messages[len(current_messages) :]
    else:
        delta = output_messages

    nudge = build_fetch_retry_nudge_messages(delta) if web_on else []
    if nudge:
        delta = list(delta) + nudge

    return {
        "messages": delta,
        "pending_tool_calls": False,
        "execution_approved": None,
    }
