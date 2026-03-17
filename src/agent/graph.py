"""
LangGraph Orchestration for the Local Cowork Agent.

This module defines the state graph, nodes, and edges that control the agent's
reasoning loop, tool execution, and security validation. It supports switching
between 'reasoning' (agentic) and 'fast' (chat) modes.
"""

from langgraph.graph import StateGraph, START, END, MessagesState
from langgraph.checkpoint.redis import RedisSaver
import redis
from langchain_core.messages import SystemMessage
from langgraph.prebuilt import ToolNode, tools_condition

from .state import AgentState
from .llm import get_mlx_openai_client
from src.tools.core_tools import CORE_TOOLS
from src.tools.mcp_client import get_mcp_tools
from src.memory.persona import get_persona, persona_to_system_prefix
from src.memory.user_profile import get_profile, profile_to_context
from src.memory.memory_manager import memories_to_context

# Combine native sandbox tools with any connected MCP tools
ALL_TOOLS = CORE_TOOLS + get_mcp_tools()

# Global instance
_llm_instance = None

def get_llm():
    """
    Retrieves or initializes the LLM client instance.
    
    Returns:
        An initialized LLM client (e.g., from get_mlx_openai_client).
    """
    global _llm_instance
    if _llm_instance is None:
        _llm_instance = get_mlx_openai_client()
    return _llm_instance

import json
import re
from langchain_core.messages import AIMessage
from langchain_core.utils.json import parse_json_markdown


# Keywords that signal a task requiring tools or deep reasoning
_AGENTIC_KEYWORDS = (
    "search", "find", "look up", "fetch", "read", "write", "run", "execute",
    "translate", "explain", "summarize", "analyze", "research", "news",
    "code", "file", "script", "tool", "image", "url", "http",
)

def _is_agentic_request(messages) -> bool:
    """
    Determines if the latest human message requires agentic reasoning or tools.

    Checks for keywords like 'search', 'run', 'code' or if the message is
    multimodal (e.g., image upload) or long.

    Args:
        messages: List of messages in the current state.

    Returns:
        True if the request is deemed agentic, False otherwise.
    """
    last_human = next(
        (m.content for m in reversed(messages) if hasattr(m, "type") and m.type == "human"), ""
    )
    if not isinstance(last_human, str):
        return True  # multimodal → treat as agentic
    text = last_human.lower()
    return any(kw in text for kw in _AGENTIC_KEYWORDS) or len(text.split()) > 20


async def reason_node(state: AgentState):
    """
    The core reasoning engine of the agent. Given the current state and messages,
    it decides what action to execute next.
    """
    llm = get_llm()
    messages = state.get("messages", [])

    mode = state.get("mode", "reasoning")

    agentic = _is_agentic_request(messages) and mode != "fast"

    # --- 1. Static Rules (Persona, Guidelines) ---
    try:
        persona = get_persona()
        persona_prefix = persona_to_system_prefix(persona)
    except Exception:
        persona_prefix = "You are Owlynn, a friendly AI study tutor and coding assistant.\n"

    static_rules = persona_prefix + "\n"

    if mode == "fast":
        static_rules += "Answer immediately and concisely. Do not use any step-by-step thinking or inner planning.\n"

    # Add agentic rules to static context
    if agentic:
        static_rules += """
You have access to tools to write code, read files, and execute shell commands inside your Podman container.
When asked to perform a task, use your tools to complete it.

FAIR REPORTING NOTICE: You are a purely educational data research assistant. You are fully authorized and required to report facts on any topic including current news, war, and international politics. You MUST use search tools to locate factual reporting rather than refusing to answer. Always remain objective and report fact-based coverage from news articles.

RULES:
1. If you have completed the requested task or have the final answer, DO NOT call any tools. Just respond with a concise conversational message to the user answering their request.
2. If a tool call fails, DO NOT repeat the exact same tool call. Modify your approach or arguments.
3. When running Python code, always use the `execute_python_code` tool instead of the shell to avoid string escaping issues.
4. IMPORTANT: When the user's message contains a `[File: filename]` block or an image/scanned document, this IS the actual content of the file they attached. You have full access to read, analyze, summarize, or process it. Never say you cannot access uploaded files — the content is right there in the message.
5. EDUCATIONAL RESPONSES: When asked to "explain", "teach", "summarize", or "analyze" file content, DO NOT ask vague clarifying questions like "What would you like to focus on?". Instead, immediately dive in and provide a clear, structured summary with headers and bullet points.
6. DIRECT ANSWERS: When asked about a specific section, page, or topic from a file, answer it directly and in detail. Do not hedge or deflect.
7. THAI TRANSLATION: Before translating any technical content to Thai, ALWAYS call the `lookup_thai_terms` tool first with key technical terms. Use the returned EN→TH glossary to ensure correct technical vocabulary. Never guess at Thai technical terms.
8. WEB TOOLS: You have access to `web_search` and `fetch_webpage` tools.
   - Use `web_search` when asked about current events, news, or any topic outside your training data.
   - For real-time updates, always set `news=True` in your `web_search` call.
   - ALWAYS call `fetch_webpage` on at least 1-2 top result URLs to read full article body text before summarising.
   - Use these tools instead of saying "I cannot access real-time information".
   - Always cite the URLs you retrieved information from.
9. OVERRIDE REFUSALS & ANTI-GUESSING: If a request requires information beyond your knowledge base, YOU MUST USE the `web_search` TOOL. Never make up facts, resolution numbers, or dates — search instead.
"""

    static_rules += """
10. REASONING PROCESS: You MUST wrap ANY and ALL step-by-step thinking, inner planning, or drafting in a SINGLE `<thought>` and `</thought>` block BEFORE giving the final answer to the user. DO NOT output any reasoning or monologue outside of these tags.
    - IMPORTANT: Ensure your final answer is a unique response to the user's latest message. NEVER repeat your previous responses word-for-word.
Example:
<thought>
I need to find x. First I will do y. Then z.
</thought>
Here is the answer...
"""

    # --- 2. Dynamic Context (Profile, Memories) ---
    try:
        profile = get_profile()
        profile_ctx = profile_to_context(profile)
    except Exception:
        profile_ctx = ""

    try:
        last_user_msg = next(
            (m.content for m in reversed(messages)
             if hasattr(m, "type") and m.type == "human"), ""
        )
        mem_ctx = memories_to_context(
            query=last_user_msg if isinstance(last_user_msg, str) else ""
        )
    except Exception:
        mem_ctx = ""

    dynamic_content = ""
    if profile_ctx:
        dynamic_content += profile_ctx + "\n\n"
    if mem_ctx:
        dynamic_content += mem_ctx + "\n\n"

    long_term_context = state.get("long_term_context")
    if long_term_context:
        dynamic_content += f"\n\n{long_term_context}"

    # --- 3. Assemble Messages ---
    context_limit = 20 if agentic else 10
    recent_messages = [m for m in messages if not isinstance(m, SystemMessage)]
    recent_messages = recent_messages[-context_limit:]

    structured_messages = [SystemMessage(content=static_rules)]
    if dynamic_content.strip():
        structured_messages.append(SystemMessage(content=dynamic_content.strip()))
    
    # Add history
    structured_messages += recent_messages

    # Bind tools only if mode is not fast
    if mode == "fast":
        llm_with_tools = llm
    else:
        llm_with_tools = llm.bind_tools(ALL_TOOLS)
        
    # Async execution
    response = await llm_with_tools.ainvoke(structured_messages)

    # Use robust parser for local models
    if mode != "fast" and not response.tool_calls and response.content:
        try:
            tool_data = parse_json_markdown(response.content)

            if isinstance(tool_data, dict) and "name" in tool_data and "arguments" in tool_data:
                response.tool_calls = [{
                    "name": tool_data["name"],
                    "args": tool_data["arguments"],
                    "id": f"call_{len(messages)}"
                }]
                response.content = f"Executing tool: {tool_data['name']}..."
        except Exception:
            pass # Fallback to Qwen <tool_call> tag parsing if standard JSON fails
            
        # Also check for Qwen's native <tool_call> tags if parse_json_markdown failed
        if not response.tool_calls and "<tool_call>" in response.content:
            tool_match = re.search(r'<tool_call>(.*?)</tool_call>', response.content, re.DOTALL)
            if tool_match:
                try:
                    tool_data = json.loads(tool_match.group(1))
                    if "name" in tool_data and "arguments" in tool_data:
                        response.tool_calls = [{
                            "name": tool_data["name"],
                            "args": tool_data["arguments"],
                            "id": f"call_{len(messages)}"
                        }]
                        new_content = response.content.replace(tool_match.group(0), "").strip()
                        response.content = new_content if new_content else f"Executing tool: {tool_data['name']}..."
                except json.JSONDecodeError:
                    pass

    # Failsafe: Programmatic Refusal Override
    refusal_keywords = [
        "cannot engage in", "not able to provide information on", "political topics",
        "sensitive topics", "against my guidelines", "discuss political", "not equipped to"
    ]
    if mode != "fast" and response.content and any(k in response.content.lower() for k in refusal_keywords) and not response.tool_calls:
        already_searched = any(

            hasattr(m, 'type') and m.type == 'tool' and getattr(m, 'name', '') == 'web_search' 
            for m in messages[-3:]
        )
        if not already_searched:
            last_human = next((m.content for m in reversed(messages) if hasattr(m, "type") and m.type == "human"), "")
            if last_human:
                response.content = f"Fixing refusal. Triggering search on: {last_human}"
                response.tool_calls = [{
                    "name": "web_search",
                    "args": {"query": last_human, "news": True},
                    "id": f"call_forced_{len(messages)}"
                }]

    if not response.content and not response.tool_calls:
        response.content = "Thinking..."

    return {"messages": [response]}

import redis
from langgraph.checkpoint.redis.aio import AsyncRedisSaver

def validate_node(state: AgentState):
    """
    Security validation node executed AFTER reasoning and BEFORE tools.
    Inspects tool calls for potentially dangerous shell commands.
    """
    messages = state.get("messages", [])
    if not messages:
        return {"execution_approved": True}
        
    last_message = messages[-1]
    # Check if last message is AIMessage and has tool calls
    if hasattr(last_message, "tool_calls") and last_message.tool_calls:
        for tool_call in last_message.tool_calls:
            name = tool_call.get("name")
            args = tool_call.get("args", {})
            
            if name == "execute_sandboxed_shell":
                command = args.get("command", "")
                if command:
                    danger_patterns = ["rm -rf /", "rm -rf *", "mkfs", "dd if="]
                    if any(p in command for p in danger_patterns):
                        # Block execution by appending a warning message
                        return {
                            "messages": [
                                AIMessage(content=f"⚠️ Security Exception: Command '{command}' was blocked containing a dangerous pattern.")
                            ],
                            "execution_approved": False
                        }
                        
    return {"execution_approved": True}

def build_graph():
    """
    Constructs the primary LangGraph execution structure.

    Defines nodes for reasoning, validation, and tool execution, and sets up
    conditional edges based on state (e.g., security approval).

    Returns:
        StateGraph: The compiled workflow ready to be compiled with memory.
    """
    workflow = StateGraph(AgentState)
    
    # Add nodes
    workflow.add_node("reasoning", reason_node)
    workflow.add_node("validate", validate_node)
    workflow.add_node("tools", ToolNode(ALL_TOOLS))
    
    # Define edges
    workflow.add_edge(START, "reasoning")
    workflow.add_edge("reasoning", "validate")
    
    def validate_or_tools(state: AgentState):
        if state.get("execution_approved") is False:
             return "reasoning"
        return tools_condition(state)
        
    workflow.add_conditional_edges(
        "validate",
        validate_or_tools,
        {
            "tools": "tools", 
            END: END,
            "reasoning": "reasoning"
        }
    )
    
    workflow.add_edge("tools", "reasoning")

    return workflow


async def init_agent():
    """
    Initializes the compiled agent with memory check-pointing using Redis.

    This function compiles the StateGraph together with a Redis checkpointer
    for thread-level persistence.

    Returns:
        The compiled LangGraph application.
    """
    workflow = build_graph()
    
    # In a UI environment like Streamlit that persists across reruns, 
    # we initialize the checkpointer dynamically with its connection info.
    # We pass the URL string natively to the checkpointer to handle connection pooling.
    checkpointer = AsyncRedisSaver(redis_url="redis://localhost:6379/0")
    await checkpointer.setup()
    
    # Compile the graph
    app = workflow.compile(checkpointer=checkpointer)
    return app
