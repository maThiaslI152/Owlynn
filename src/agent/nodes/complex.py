import asyncio
import re

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.prebuilt import ToolNode

from src.agent.state import AgentState
from src.agent.llm import get_large_llm
from src.agent.response_styles import style_instruction_for_prompt
from src.agent.tool_sets import COMPLEX_TOOLS_NO_WEB, COMPLEX_TOOLS_WITH_WEB
from src.agent.lm_studio_compat import with_system_for_local_server


def _strip_thinking_tags(text: str) -> str:
    """Remove <think>...</think> blocks from Qwen3.5 reasoning output."""
    if not text:
        return text
    cleaned = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
    return cleaned if cleaned else text

COMPLEX_PROMPT = """You are Owlynn, an expert reasoning agent. Think step by step before answering.
Current date: {current_date}

Behaviors:
- If a request is clearly ambiguous or missing critical details, use ask_user once to clarify. But if you can reasonably infer intent from context or memory, just do the work. Don't over-ask.
- When a request matches a known skill (research, summarize, briefing), use invoke_skill to get the workflow, then follow it.
- Be thorough and accurate. Show your reasoning clearly.

User memory context:
{memory_context}

User persona summary:
{persona}

Guidelines:
- If writing code, include comments
- If reasoning through a problem, show your thinking clearly
- Never fabricate facts — if uncertain, say so{style_hint}"""

# Models sometimes mimic bracketed “use tool X” system text instead of emitting real tool_calls; forbid that.
_TOOL_CALL_DISCIPLINE = """
Tool discipline: You have native function/tool calling in this API. Whenever you need file contents, web results, or sandbox code, you **must** emit an actual tool/function call; the UI executes it automatically. Do **not** answer with only prose like “use read_workspace_file…” or echo bracketed instructions — call the tool, wait for results, then write your answer from those results."""

COMPLEX_TOOL_GUIDANCE_WEB = (
    """
You have tools to help answer accurately:

1) web_search / fetch_webpage: Search the web and fetch page content.
2) read_workspace_file / write_workspace_file / edit_workspace_file: Read, write, and edit files.
3) list_workspace_files / delete_workspace_file: List and delete files.
4) recall_memories: Search long-term memories about the user.
5) notebook_run / notebook_reset: Python REPL for calculations and data processing.
6) create_docx / create_xlsx / create_pptx / create_pdf: Generate documents.
7) todo_add / todo_list / todo_complete: Manage the user's task list.
8) list_skills / invoke_skill: Use reusable prompt templates.
9) ask_user: Ask a clarifying question when you need more info.

Rules:
- Ground claims in tool output only. Do not invent facts or URLs.
- Use [1], [2] citations from fetch_webpage excerpts.
- If tools return nothing useful, say so honestly."""
    + _TOOL_CALL_DISCIPLINE
)

COMPLEX_TOOL_GUIDANCE_NO_WEB = (
    """
You have tools (web search is off for this chat):
1) read_workspace_file / write_workspace_file / edit_workspace_file: File management.
2) list_workspace_files / delete_workspace_file: List and delete files.
3) recall_memories: Search long-term memories.
4) notebook_run / notebook_reset: Python REPL for calculations.
5) create_docx / create_xlsx / create_pptx / create_pdf: Generate documents.
6) todo_add / todo_list / todo_complete: Manage tasks.
7) list_skills / invoke_skill: Use reusable prompt templates.
8) ask_user: Ask a clarifying question.

Summarize tool results clearly for the user."""
    + _TOOL_CALL_DISCIPLINE
)


def _web_search_tool_output_has_results(content: str) -> bool:
    """True when web_search returned normal hit listings (not structured failure)."""
    c = content or ""
    if "Unable to retrieve online results" in c:
        return False
    if c.startswith("[web_search]") and ("Error" in c or "Unable" in c):
        return False
    if "blocked_by_captcha" in c:
        return False
    return ("🔍" in c or "search results for" in c) and "URL:" in c


def _synthetic_answer_from_web_search_tool(content: str) -> str:
    """
    When the LLM returns empty after a successful web_search, surface the tool text
    so the user still gets a usable answer in the UI.
    """
    c = (content or "").strip()
    if not c:
        return (
            "I ran **web_search** but the tool returned no text. "
            "Try again or narrow the query."
        )
    pref = (
        "The model returned an empty message after **web_search**, so here is the "
        "search payload directly (you can use the links below):\n\n"
    )
    cap = 4500
    if len(c) > cap:
        return pref + c[:cap] + "\n\n… [truncated]"
    return pref + c


def build_web_search_answer_nudge_messages(tool_messages: list) -> list[HumanMessage]:
    """After a successful web_search, remind the model it must write the final answer (non-empty)."""
    if not tool_messages:
        return []
    for m in tool_messages:
        if not isinstance(m, ToolMessage):
            continue
        if (getattr(m, "name", None) or "") != "web_search":
            continue
        c = m.content if isinstance(m.content, str) else str(m.content or "")
        if not _web_search_tool_output_has_results(c):
            continue
        return [
            HumanMessage(
                content=(
                    "[Internal reminder for assistant] **web_search** returned results above. "
                    "You must now write a complete answer for the user in plain language using those "
                    "results (definition, main ideas, optional link to the official docs). "
                    "Do not reply with empty content or only tool metadata."
                )
            )
        ]
    return []


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

    Prefers context from recent ``ToolMessage`` outputs (successful or failed ``web_search``).
    If there are no tool messages yet (first LLM turn before any tools) or no match, returns a
    generic message so the thread does not stay blank.
    """
    for m in reversed(messages):
        if not isinstance(m, ToolMessage):
            continue
        c = m.content if isinstance(m.content, str) else str(m.content or "")
        if (getattr(m, "name", None) or "") == "web_search":
            if _web_search_tool_output_has_results(c):
                return AIMessage(content=_synthetic_answer_from_web_search_tool(c))
            if (
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


def _flatten_human_content(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and block.get("type") == "text":
                parts.append(str(block.get("text", "")))
        return "\n".join(parts)
    return str(content or "")


def _latest_user_text(messages: list) -> str:
    for m in reversed(messages):
        if isinstance(m, HumanMessage):
            return _flatten_human_content(m.content)
    return ""


def _workspace_paths_from_text(text: str) -> list[str]:
    """Filenames from chat upload injections (server + legacy wording)."""
    paths: list[str] = []
    seen: set[str] = set()
    for pat in (
        r"\[Workspace file\s+`([^`]+)`",
        r"Workspace file\s+`([^`]+)`",
        r"\[File:\s*([^\]\n]+?)\s+uploaded to workspace",
    ):
        for m in re.finditer(pat, text, re.IGNORECASE):
            p = (m.group(1) or "").strip()
            if p and p not in seen:
                seen.add(p)
                paths.append(p)
    return paths


def _user_intent_needs_workspace_read(text: str) -> bool:
    t = (text or "").lower()
    needles = (
        "summarize",
        "summary",
        "study",
        "read this",
        "read the",
        "explain",
        "what does",
        "what is",
        "help me",
        "tell me",
        "analyze",
        "slide",
        "pdf",
        "document",
        "this file",
        "lecture",
        "chapter",
        "content of",
        "outline",
        "key point",
        "notes",
    )
    return any(n in t for n in needles)


def _looks_like_prose_tool_stall(response: AIMessage) -> bool:
    """Local models often answer with 'use read_workspace_file…' instead of tool_calls."""
    if getattr(response, "tool_calls", None):
        return False
    c = str(getattr(response, "content", "") or "").strip()
    if not c:
        return True
    low = c.lower()
    if "read_workspace_file" in low:
        return True
    if "uploaded to workspace" in low and ("tool" in low or "read_" in low):
        return True
    if len(c) < 420:
        return True
    return False


async def _auto_read_workspace_bundle(paths: list[str]) -> str:
    """Read files via the same tool implementation the graph uses (thread pool)."""
    from src.tools.core_tools import read_workspace_file
    sections: list[str] = []
    per_cap = 28_000
    for raw in paths[:3]:
        p = raw.strip()
        if not p:
            continue
        try:
            body = await asyncio.to_thread(read_workspace_file.invoke, {"filename": p})
        except Exception as e:
            body = f"[read_workspace_file error for {p!r}: {e}]"
        b = str(body)
        if len(b) > per_cap:
            b = (
                b[:per_cap]
                + f"\n\n[Truncated after {per_cap} characters; full file remains in the workspace.]"
            )
        sections.append(f"### File: {p}\n{b}")
    if not sections:
        return ""
    return (
        "[Automated workspace read — files were read by the host because the model did not emit "
        "tool calls. Use ONLY the text below to answer the user now — do not ask them to run a tool.]\n\n"
        + "\n\n".join(sections)
    )


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
        current_date=__import__('datetime').date.today().strftime('%B %d, %Y'),
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
        budget = state.get("token_budget") or 4096
        response = await large_llm.bind(max_tokens=budget).ainvoke(prompt_messages)
        return {
            "messages": [AIMessage(content=response.content)],
            "model_used": "large",
            "pending_tool_calls": False,
        }

    tools = COMPLEX_TOOLS_WITH_WEB if web_on else COMPLEX_TOOLS_NO_WEB
    budget = state.get("token_budget") or 4096
    large_llm = (await get_large_llm()).bind_tools(tools).bind(max_tokens=budget)
    response = await large_llm.ainvoke(prompt_messages)
    has_tool_calls = bool(getattr(response, "tool_calls", None))
    if not has_tool_calls and not str(getattr(response, "content", "") or "").strip():
        response = _fallback_for_blank_response(
            thread_messages, web_search_enabled=web_on
        )
        has_tool_calls = bool(getattr(response, "tool_calls", None))

    out_messages: list = [response]

    # Local OpenAI-compatible servers often return plain text (“use read_workspace_file…”) instead
    # of structured tool_calls. When uploads are clearly present, read the files here and re-prompt once.
    if not has_tool_calls:
        utext = _latest_user_text(thread_messages)
        paths = _workspace_paths_from_text(utext)
        if (
            paths
            and _user_intent_needs_workspace_read(utext)
            and _looks_like_prose_tool_stall(response)
        ):
            bundle = await _auto_read_workspace_bundle(paths)
            if bundle.strip():
                nudge = HumanMessage(content=bundle)
                second_prompt = with_system_for_local_server(
                    system, thread_messages + [nudge]
                )
                response = await large_llm.ainvoke(second_prompt)
                has_tool_calls = bool(getattr(response, "tool_calls", None))
                if not has_tool_calls and not str(getattr(response, "content", "") or "").strip():
                    response = _fallback_for_blank_response(
                        thread_messages + [nudge], web_search_enabled=web_on
                    )
                    has_tool_calls = bool(getattr(response, "tool_calls", None))
                out_messages = [nudge, response]

    # Strip <think> tags from the final response before returning
    for i, msg in enumerate(out_messages):
        if isinstance(msg, AIMessage) and msg.content and not getattr(msg, "tool_calls", None):
            cleaned = _strip_thinking_tags(msg.content)
            if cleaned != msg.content:
                out_messages[i] = AIMessage(content=cleaned)

    return {
        "messages": out_messages,
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
    ws_nudge = build_web_search_answer_nudge_messages(delta) if web_on else []
    if nudge or ws_nudge:
        delta = list(delta) + nudge + ws_nudge

    return {
        "messages": delta,
        "pending_tool_calls": False,
        "execution_approved": None,
    }
