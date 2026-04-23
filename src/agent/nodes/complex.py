import asyncio
import json
import logging
import re

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.prebuilt import ToolNode

from src.agent.state import AgentState
from src.agent.llm import get_large_llm, get_medium_llm, get_cloud_llm, CloudUnavailableError
from src.agent.swap_manager import ModelSwapError
from src.agent.response_styles import style_instruction_for_prompt
from src.agent.tool_sets import (
    COMPLEX_TOOLS_NO_WEB,
    COMPLEX_TOOLS_WITH_WEB,
    resolve_tools,
)
from src.agent.lm_studio_compat import is_local_server, with_system_for_local_server
from src.agent.anonymization import anonymize, deanonymize
from src.memory.user_profile import get_profile

logger = logging.getLogger(__name__)

# Context window for the large model (Qwen3.5 9B in LM Studio)
_LARGE_CONTEXT_WINDOW = 100000
# Minimum output tokens — if less than this is available, we still try
_MIN_OUTPUT_TOKENS = 512
# Safety margin to avoid hitting the exact limit
_CONTEXT_SAFETY_MARGIN = 256


def _estimate_message_tokens(messages: list) -> int:
    """
    Estimate token count for a list of LangChain messages.
    Uses a rough heuristic: ~4 chars per token for English/code,
    ~2 chars per token for Thai/CJK.  Good enough for budget capping
    without needing a real tokenizer (which would add latency).
    """
    total_chars = 0
    for msg in messages:
        content = getattr(msg, "content", None) or ""
        if isinstance(content, list):
            for block in content:
                if isinstance(block, str):
                    total_chars += len(block)
                elif isinstance(block, dict):
                    total_chars += len(str(block.get("text", "")))
        else:
            total_chars += len(str(content))
        # Overhead per message (role tokens, formatting)
        total_chars += 20

    # Heuristic: average ~3.5 chars per token (blend of English and Thai)
    return int(total_chars / 3.5)


def _cap_budget_to_context(prompt_messages: list, requested_budget: int) -> int:
    """
    Given the assembled prompt and a requested output budget, cap it so that
    input + output doesn't exceed the context window.
    """
    input_tokens = _estimate_message_tokens(prompt_messages)
    available = _LARGE_CONTEXT_WINDOW - input_tokens - _CONTEXT_SAFETY_MARGIN
    capped = max(min(requested_budget, available), _MIN_OUTPUT_TOKENS)
    return capped


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
- When a request matches a known skill, use invoke_skill to get the workflow, then follow it. Available skills:
  • data_visualization (triggers: chart, graph, plot, visualize, dashboard)
  • report_generator (triggers: create report, write report, generate report)
  • research_assistant (triggers: research, deep dive, investigate)
  • summarize_document (triggers: summarize, summary, key points)
  • brainstorm (triggers: brainstorm, ideas, suggest, what if)
  • presentation_builder (triggers: create presentation, slides, deck, pptx)
  • email_draft (triggers: draft email, write email, compose email)
  • content_rewriter (triggers: rewrite, rephrase, improve writing)
  • meeting_notes (triggers: meeting notes, action items, minutes)
  • morning_briefing (triggers: briefing, morning, daily summary)
  • visual_comparison (triggers: compare, versus, side by side)
  Always call invoke_skill with the skill name when the user's request matches these triggers.
- Be thorough and accurate. Show your reasoning clearly.
- If project instructions are provided below, they take HIGHEST PRIORITY. Tailor your tone, focus, and approach to match the project's purpose. The project context defines what you should specialize in for this conversation.

User memory context:
{memory_context}

User persona summary:
{persona}

Guidelines:
- If writing code, include comments
- If reasoning through a problem, show your thinking clearly
- Never fabricate facts — if uncertain, say so{style_hint}"""

# Models sometimes mimic bracketed "use tool X" system text instead of emitting real tool_calls; forbid that.
_TOOL_CALL_DISCIPLINE = """
Tool discipline: You have native function/tool calling in this API. Whenever you need file contents, web results, or sandbox code, you **must** emit an actual tool/function call; the UI executes it automatically. Do **not** answer with only prose like "use read_workspace_file…" or echo bracketed instructions — call the tool, wait for results, then write your answer from those results."""

COMPLEX_TOOL_GUIDANCE_WEB = (
    """
You have tools to help answer accurately:

1) web_search / fetch_webpage: Search the web and fetch page content.
2) read_workspace_file / write_workspace_file / edit_workspace_file: Read, write, and edit files.
3) list_workspace_files / delete_workspace_file: List and delete files.
4) recall_memories: Search long-term memories about the user. When in a project context, this also searches the project's indexed knowledge base.
5) notebook_run / notebook_reset: Python REPL for calculations and data processing. Files are in the WORKSPACE_DIR variable — use f"{WORKSPACE_DIR}/filename.csv" for file paths.
6) create_docx / create_xlsx / create_pptx / create_pdf: Generate documents.
7) todo_add / todo_list / todo_complete: Manage the user's task list.
8) list_skills / invoke_skill: Use reusable prompt templates.
9) ask_user: Ask a clarifying question when you need more info.

Rules:
- Ground claims in tool output only. Do not invent facts or URLs.
- Use [1], [2] citations from fetch_webpage excerpts.
- If tools return nothing useful, say so honestly.
- When working in a project, prefer project knowledge and workspace files over web search for project-specific questions."""
    + _TOOL_CALL_DISCIPLINE
)

COMPLEX_TOOL_GUIDANCE_NO_WEB = (
    """
You have tools (web search is off for this chat):
1) read_workspace_file / write_workspace_file / edit_workspace_file: File management.
2) list_workspace_files / delete_workspace_file: List and delete files.
3) recall_memories: Search long-term memories.
4) notebook_run / notebook_reset: Python REPL for calculations. Files are in the WORKSPACE_DIR variable — use f"{WORKSPACE_DIR}/filename.csv" for file paths.
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
                        "I couldn't verify this online right now because web search providers returned "
                        "errors or bot challenges. I did not find reliable live sources in this run. "
                        "If you want, I can retry with a narrower query, a different provider, or use "
                        "another source you provide."
                    )
                )
    if web_search_enabled:
        return AIMessage(
            content=(
                "I didn't get a usable reply from the model this time (empty response). "
                "Try rephrasing or shortening your message, confirm your LLM server is running, "
                "or retry. If you need live web facts, we can try again once the model responds normally."
            )
        )
    return AIMessage(
        content=(
            "I didn't get a usable reply from the model this time (empty response). "
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
    # With 100k context, we can afford more content per file
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


def _trim_tool_history(messages: list, max_tool_cycles: int = 6) -> list:
    """
    Compress older tool call/result cycles to keep the conversation within
    the context window.  Keeps the first human message and the last
    `max_tool_cycles` full cycles (AI tool_call + ToolMessage pairs).
    Older tool results are replaced with a one-line summary.
    """
    if len(messages) <= 6:
        return messages  # Short enough, no trimming needed

    # Find all tool message indices
    tool_indices = [i for i, m in enumerate(messages) if isinstance(m, ToolMessage)]
    if len(tool_indices) <= max_tool_cycles:
        return messages  # Few enough cycles, keep all

    # Indices of tool messages to summarize (all except the last N)
    old_tool_indices = set(tool_indices[:-max_tool_cycles])

    # Also find the AI messages that triggered those old tool calls
    old_ai_indices = set()
    for ti in old_tool_indices:
        # The AI message with tool_calls is typically right before the tool message(s)
        for j in range(ti - 1, -1, -1):
            if isinstance(messages[j], AIMessage) and getattr(messages[j], 'tool_calls', None):
                old_ai_indices.add(j)
                break

    trimmed = []
    for i, msg in enumerate(messages):
        if i in old_tool_indices:
            # Replace old tool output with a compact summary
            content = msg.content if isinstance(msg.content, str) else str(msg.content or "")
            tool_name = getattr(msg, 'name', 'tool') or 'tool'
            if "Error" in content[:100]:
                summary = f"[{tool_name}: returned an error]"
            else:
                summary = f"[{tool_name}: completed, {len(content)} chars output]"
            trimmed.append(ToolMessage(
                content=summary,
                tool_call_id=msg.tool_call_id,
                name=getattr(msg, 'name', None)
            ))
        elif i in old_ai_indices:
            # Keep the AI message but it needs to stay for the tool_call_id chain
            trimmed.append(msg)
        else:
            trimmed.append(msg)

    return trimmed


async def complex_llm_node(state: AgentState) -> AgentState:
    """
    LLM reasoning node for the cyclic secure tool flow.
    It either answers directly or emits tool calls for the security proxy.

    Supports route-based model selection (9.1), cloud anonymization (9.2),
    dynamic tool binding (9.3), tiered fallback chains (9.4), and
    cloud token usage tracking (9.5).
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

    # Trim conversation history to fit context window.
    trimmed_messages = _trim_tool_history(thread_messages)

    # ── 9.1: Route-based model selection ─────────────────────────────────
    route = state.get("route") or "complex-default"
    model_label = "medium-default"
    anon_mapping = None
    api_tokens = None
    profile = get_profile()

    # Keep a pre-anonymization copy for cloud fallback paths.
    original_trimmed_messages = list(trimmed_messages)

    # ── 9.2: Anonymization for cloud route ───────────────────────────────
    if route == "complex-cloud" and profile.get("cloud_anonymization_enabled", True):
        anon_ctx = {
            "name": profile.get("name", ""),
            "custom_sensitive_terms": profile.get("custom_sensitive_terms", []),
        }
        # Anonymize system text
        system_text, anon_mapping = anonymize(system_text, anon_ctx)
        system = SystemMessage(content=system_text)
        # Anonymize each message content
        anon_messages = []
        for msg in trimmed_messages:
            content = msg.content
            if isinstance(content, str):
                content, msg_mapping = anonymize(content, anon_ctx)
                if anon_mapping is not None:
                    anon_mapping.update(msg_mapping)
                else:
                    anon_mapping = msg_mapping
            anon_messages.append(type(msg)(content=content))
        trimmed_messages = anon_messages

    # ── 9.1 continued: Determine base_url for message format decision ────
    if route == "complex-cloud":
        base_url = profile.get("cloud_llm_base_url", "https://api.deepseek.com/v1")
    else:
        base_url = profile.get("small_llm_base_url", "http://127.0.0.1:1234/v1")

    if is_local_server(base_url):
        prompt_messages = with_system_for_local_server(system, trimmed_messages)
    else:
        prompt_messages = [system, *trimmed_messages]

    # ── tools_off mode (no tools) ────────────────────────────────────────
    fallback_chain: list[dict] = []
    loop_start_time: float | None = None
    if mode == "tools_off":
        try:
            loop_start_time = asyncio.get_running_loop().time()
            if route == "complex-cloud":
                llm = await get_cloud_llm()
                model_label = "large-cloud"
            elif route == "complex-vision":
                llm = await get_medium_llm("vision")
                model_label = "medium-vision"
            elif route == "complex-longctx":
                llm = await get_medium_llm("longctx")
                model_label = "medium-longctx"
            else:
                llm = await get_medium_llm("default")
                model_label = "medium-default"
        except (ModelSwapError, CloudUnavailableError) as e:
            logger.warning("[complex] Model %s unavailable (%s), falling back to medium-default", route, e)
            fallback_chain.append({"model": model_label or route, "status": "failed", "reason": str(e)[:120], "duration_ms": 0})
            llm = await get_medium_llm("default")
            model_label = "medium-default-fallback"
            fallback_chain.append({"model": "medium-default-fallback", "status": "success", "reason": "fallback_from_unavailable", "duration_ms": 0})

        budget = _cap_budget_to_context(prompt_messages, state.get("token_budget") or 4096)
        response = await llm.bind(max_tokens=budget).ainvoke(prompt_messages)
        return {
            "messages": [AIMessage(content=response.content)],
            "model_used": model_label,
            "pending_tool_calls": False,
            "security_decision": None,
            "security_reason": None,
            "api_tokens_used": None,
            "fallback_chain": fallback_chain,
        }

    # ── 9.3: Dynamic tool binding ────────────────────────────────────────
    selected_toolboxes = state.get("selected_toolboxes")
    if selected_toolboxes and "all" not in selected_toolboxes:
        tools = resolve_tools(selected_toolboxes, web_on)
    else:
        tools = list(COMPLEX_TOOLS_WITH_WEB if web_on else COMPLEX_TOOLS_NO_WEB)

    # Include previously-used tools from conversation history
    # to ensure ToolMessage references remain valid
    prev_tool_names: set[str] = set()
    for msg in thread_messages:
        if hasattr(msg, 'tool_calls') and msg.tool_calls:
            for tc in msg.tool_calls:
                prev_tool_names.add(tc.get('name', ''))

    if prev_tool_names:
        all_tools = COMPLEX_TOOLS_WITH_WEB if web_on else COMPLEX_TOOLS_NO_WEB
        for t in all_tools:
            if getattr(t, 'name', '') in prev_tool_names and t not in tools:
                tools.append(t)

    # ── 9.4: Tiered fallback — model acquisition ────────────────────────
    try:
        if route == "complex-cloud":
            loop_start_time = asyncio.get_running_loop().time()
            llm = await get_cloud_llm()
            model_label = "large-cloud"
            fallback_chain.append({
                "model": "large-cloud",
                "status": "success",
                "reason": "initial_route",
                "duration_ms": 0,
            })
        elif route == "complex-vision":
            loop_start_time = asyncio.get_running_loop().time()
            llm = await get_medium_llm("vision")
            model_label = "medium-vision"
            fallback_chain.append({
                "model": "medium-vision",
                "status": "success",
                "reason": "initial_route",
                "duration_ms": 0,
            })
        elif route == "complex-longctx":
            loop_start_time = asyncio.get_running_loop().time()
            llm = await get_medium_llm("longctx")
            model_label = "medium-longctx"
            fallback_chain.append({
                "model": "medium-longctx",
                "status": "success",
                "reason": "initial_route",
                "duration_ms": 0,
            })
        else:
            loop_start_time = asyncio.get_running_loop().time()
            llm = await get_medium_llm("default")
            model_label = "medium-default"
            fallback_chain.append({
                "model": "medium-default",
                "status": "success",
                "reason": "initial_route",
                "duration_ms": 0,
            })
    except (ModelSwapError, CloudUnavailableError) as e:
        logger.warning("[complex] Model %s unavailable (%s), falling back to medium-default", route, e)
        fallback_chain.append({
            "model": model_label if model_label != "medium-default" else route,
            "status": "failed",
            "reason": str(e)[:120],
            "duration_ms": 0,
        })
        llm = await get_medium_llm("default")
        model_label = "medium-default-fallback"
        fallback_chain.append({
            "model": "medium-default-fallback",
            "status": "success",
            "reason": "fallback_from_unavailable",
            "duration_ms": 0,
        })

    budget = _cap_budget_to_context(prompt_messages, state.get("token_budget") or 4096)
    bound_llm = llm.bind_tools(tools).bind(max_tokens=budget)

    # ── 9.4: Tiered fallback — LLM invocation with error handling ────────
    try:
        response = await bound_llm.ainvoke(prompt_messages)
    except Exception as e:
        error_str = str(e).lower()
        if route == "complex-cloud":
            if "429" in str(e) or "rate" in error_str:
                # Rate limit: retry after delay
                loop_start_time = asyncio.get_running_loop().time()
                await asyncio.sleep(2)
                try:
                    response = await bound_llm.ainvoke(prompt_messages)
                except Exception:
                    logger.warning("[complex] Cloud retry failed, falling back to medium-default")
                    fallback_chain.append({
                        "model": "large-cloud",
                        "status": "failed",
                        "reason": "rate_limit_retry_failed",
                        "duration_ms": max(0, int((asyncio.get_running_loop().time() - loop_start_time) * 1000)) if loop_start_time else 0,
                    })
                    llm = await get_medium_llm("default")
                    prompt_messages = with_system_for_local_server(system, original_trimmed_messages)
                    budget = _cap_budget_to_context(prompt_messages, state.get("token_budget") or 4096)
                    fb_start = asyncio.get_running_loop().time()
                    response = await llm.bind_tools(tools).bind(max_tokens=budget).ainvoke(prompt_messages)
                    model_label = "medium-default-fallback"
                    fallback_chain.append({
                        "model": "medium-default-fallback",
                        "status": "success",
                        "reason": "fallback_rate_limit",
                        "duration_ms": max(0, int((asyncio.get_running_loop().time() - fb_start) * 1000)),
                    })
            elif "401" in str(e) or "403" in str(e):
                # Auth error: fall back with note
                fallback_chain.append({
                    "model": "large-cloud",
                    "status": "failed",
                    "reason": "auth_error_401_403",
                    "duration_ms": max(0, int((asyncio.get_running_loop().time() - (loop_start_time or asyncio.get_running_loop().time())) * 1000)) if loop_start_time else 0,
                })
                llm = await get_medium_llm("default")
                prompt_messages = with_system_for_local_server(system, original_trimmed_messages)
                budget = _cap_budget_to_context(prompt_messages, state.get("token_budget") or 4096)
                fb_start = asyncio.get_running_loop().time()
                response = await llm.bind_tools(tools).bind(max_tokens=budget).ainvoke(prompt_messages)
                response = AIMessage(
                    content=(response.content or "")
                    + "\n\n⚠️ Note: DeepSeek API key may be invalid. Check Settings → Profile → Cloud section."
                )
                model_label = "medium-default-fallback"
                fallback_chain.append({
                    "model": "medium-default-fallback",
                    "status": "success",
                    "reason": "fallback_auth_error",
                    "duration_ms": max(0, int((asyncio.get_running_loop().time() - fb_start) * 1000)),
                })
            else:
                logger.warning("[complex] Cloud error (%s), falling back to medium-default", e)
                fallback_chain.append({
                    "model": "large-cloud",
                    "status": "failed",
                    "reason": str(e)[:120],
                    "duration_ms": max(0, int((asyncio.get_running_loop().time() - (loop_start_time or asyncio.get_running_loop().time())) * 1000)) if loop_start_time else 0,
                })
                llm = await get_medium_llm("default")
                prompt_messages = with_system_for_local_server(system, original_trimmed_messages)
                budget = _cap_budget_to_context(prompt_messages, state.get("token_budget") or 4096)
                fb_start = asyncio.get_running_loop().time()
                response = await llm.bind_tools(tools).bind(max_tokens=budget).ainvoke(prompt_messages)
                model_label = "medium-default-fallback"
                fallback_chain.append({
                    "model": "medium-default-fallback",
                    "status": "success",
                    "reason": "fallback_generic_cloud_error",
                    "duration_ms": max(0, int((asyncio.get_running_loop().time() - fb_start) * 1000)),
                })
        elif route == "complex-vision":
            logger.warning("[complex] Vision model failed (%s), falling back to medium-default", e)
            fallback_chain.append({
                "model": "medium-vision",
                "status": "failed",
                "reason": str(e)[:120],
                "duration_ms": max(0, int((asyncio.get_running_loop().time() - (loop_start_time or asyncio.get_running_loop().time())) * 1000)) if loop_start_time else 0,
            })
            llm = await get_medium_llm("default")
            prompt_messages = with_system_for_local_server(system, trimmed_messages)
            budget = _cap_budget_to_context(prompt_messages, state.get("token_budget") or 4096)
            fb_start = asyncio.get_running_loop().time()
            response = await llm.bind_tools(tools).bind(max_tokens=budget).ainvoke(prompt_messages)
            model_label = "medium-default-fallback"
            fallback_chain.append({
                "model": "medium-default-fallback",
                "status": "success",
                "reason": "fallback_vision_failed",
                "duration_ms": max(0, int((asyncio.get_running_loop().time() - fb_start) * 1000)),
            })
        elif route == "complex-longctx":
            # Try cloud first, then medium-default
            try:
                loop_start_time = asyncio.get_running_loop().time()
                llm = await get_cloud_llm()
                budget = _cap_budget_to_context([system, *trimmed_messages], state.get("token_budget") or 4096)
                response = await llm.bind_tools(tools).bind(max_tokens=budget).ainvoke([system, *trimmed_messages])
                model_label = "large-cloud-fallback"
                fallback_chain.append({
                    "model": "large-cloud-fallback",
                    "status": "success",
                    "reason": "longctx_cloud_escalation",
                    "duration_ms": max(0, int((asyncio.get_running_loop().time() - loop_start_time) * 1000)),
                })
            except Exception:
                fallback_chain.append({
                    "model": "medium-longctx",
                    "status": "failed",
                    "reason": "longctx_local_unavailable_cloud_failed",
                    "duration_ms": max(0, int((asyncio.get_running_loop().time() - (loop_start_time or asyncio.get_running_loop().time())) * 1000)) if loop_start_time else 0,
                })
                llm = await get_medium_llm("default")
                prompt_messages = with_system_for_local_server(system, trimmed_messages)
                budget = _cap_budget_to_context(prompt_messages, state.get("token_budget") or 4096)
                fb_start = asyncio.get_running_loop().time()
                response = await llm.bind_tools(tools).bind(max_tokens=budget).ainvoke(prompt_messages)
                model_label = "medium-default-fallback"
                fallback_chain.append({
                    "model": "medium-default-fallback",
                    "status": "success",
                    "reason": "fallback_last_resort",
                    "duration_ms": max(0, int((asyncio.get_running_loop().time() - fb_start) * 1000)),
                })
        else:
            raise  # medium-default failure — let it propagate

    # If we fell back from cloud, skip deanonymization — fallback model got non-anonymized input
    if "fallback" in model_label and anon_mapping:
        anon_mapping = None

    # ── 9.2 continued: Deanonymize response (before stripping think tags) ─
    if anon_mapping and route == "complex-cloud":
        if response.content:
            response = AIMessage(content=deanonymize(response.content, anon_mapping))
        if hasattr(response, 'tool_calls') and response.tool_calls:
            for tc in response.tool_calls:
                if tc.get('args'):
                    args_str = json.dumps(tc['args'])
                    args_str = deanonymize(args_str, anon_mapping)
                    tc['args'] = json.loads(args_str)

    # ── 9.5: Cloud token usage tracking ──────────────────────────────────
    if route == "complex-cloud" and "fallback" not in model_label:
        usage = getattr(response, 'response_metadata', {}).get('token_usage', {})
        if not usage:
            usage = getattr(response, 'usage_metadata', {})
        if usage:
            api_tokens = {
                "prompt_tokens": usage.get("input_tokens") or usage.get("prompt_tokens", 0),
                "completion_tokens": usage.get("output_tokens") or usage.get("completion_tokens", 0),
            }

    has_tool_calls = bool(getattr(response, "tool_calls", None))
    if not has_tool_calls and not str(getattr(response, "content", "") or "").strip():
        response = _fallback_for_blank_response(
            thread_messages, web_search_enabled=web_on
        )
        has_tool_calls = bool(getattr(response, "tool_calls", None))

    out_messages: list = [response]

    # Local OpenAI-compatible servers often return plain text instead of
    # structured tool_calls. When uploads are clearly present, read the
    # files here and re-prompt once.
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
                recapped = _cap_budget_to_context(second_prompt, state.get("token_budget") or 4096)
                llm_recapped = llm.bind_tools(tools).bind(max_tokens=recapped)
                response = await llm_recapped.ainvoke(second_prompt)
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
        "model_used": model_label,
        "pending_tool_calls": bool(getattr(response, "tool_calls", None)),
        "security_decision": None,
        "security_reason": None,
        "api_tokens_used": api_tokens,
        "fallback_chain": fallback_chain,
    }


async def complex_tool_action_node(state: AgentState) -> AgentState:
    """
    Executes already-approved tool calls and appends tool outputs to the thread.
    Truncates large tool outputs to avoid blowing the context window.
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

    # Truncate large tool outputs to stay within context window.
    _MAX_TOOL_OUTPUT_CHARS = 20_000
    truncated_delta = []
    for msg in delta:
        if isinstance(msg, ToolMessage):
            content = msg.content if isinstance(msg.content, str) else str(msg.content or "")
            if len(content) > _MAX_TOOL_OUTPUT_CHARS:
                truncated = content[:_MAX_TOOL_OUTPUT_CHARS] + "\n\n[... output truncated for context window. Use read_workspace_file for full content.]"
                msg = ToolMessage(content=truncated, tool_call_id=msg.tool_call_id, name=getattr(msg, 'name', None))
        truncated_delta.append(msg)
    delta = truncated_delta

    nudge = build_fetch_retry_nudge_messages(delta) if web_on else []
    ws_nudge = build_web_search_answer_nudge_messages(delta) if web_on else []

    # Nudge the model to retry if a tool call failed with an error
    error_nudge = []
    for msg in delta:
        if isinstance(msg, ToolMessage):
            content = msg.content if isinstance(msg.content, str) else str(msg.content or "")
            tool_name = getattr(msg, 'name', '') or ''
            if "Error" in content and ("Field required" in content or "No code provided" in content):
                error_nudge.append(
                    HumanMessage(
                        content=(
                            f"[Internal reminder] The tool call to **{tool_name}** failed because required parameters "
                            f"were missing. Please retry the tool call with the correct parameters. "
                            f"For notebook_run, you must provide the 'code' parameter with Python code."
                        )
                    )
                )
                break
            elif "FileNotFoundError" in content and tool_name == "notebook_run":
                error_nudge.append(
                    HumanMessage(
                        content=(
                            "[Internal reminder] notebook_run could not find the file. "
                            "Files are in the workspace directory. The variable WORKSPACE_DIR is pre-defined. "
                            "Use: pd.read_csv(f\"{WORKSPACE_DIR}/filename.csv\") — retry with the corrected path."
                        )
                    )
                )
                break
            elif "ModuleNotFoundError" in content and tool_name == "notebook_run":
                import re as _re
                mod_match = _re.search(r"No module named '([^']+)'", content)
                mod_name = mod_match.group(1) if mod_match else "unknown"
                error_nudge.append(
                    HumanMessage(
                        content=(
                            f"[Internal reminder] notebook_run failed because '{mod_name}' is not installed. "
                            f"Available libraries: pandas, numpy, matplotlib, seaborn, plotly, scipy, scikit-learn, "
                            f"openpyxl, xlsxwriter, pillow, sympy, chardet, tabulate, jinja2. "
                            f"Retry using only available libraries."
                        )
                    )
                )
                break
            elif "Error" in content and tool_name == "notebook_run" and "Traceback" in content:
                lines = content.strip().split('\n')
                error_line = lines[-1] if lines else "Unknown error"
                error_nudge.append(
                    HumanMessage(
                        content=(
                            f"[Internal reminder] notebook_run hit a Python error: {error_line}\n"
                            f"Common fixes: convert string columns to numeric with pd.to_numeric(col, errors='coerce'), "
                            f"strip '%' from percentage strings, handle NaN values, check column dtypes with df.dtypes. "
                            f"Please fix the code and retry."
                        )
                    )
                )
                break

    if nudge or ws_nudge or error_nudge:
        delta = list(delta) + nudge + ws_nudge + error_nudge

    return {
        "messages": delta,
        "pending_tool_calls": False,
        "execution_approved": None,
    }
