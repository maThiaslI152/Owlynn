"""
LangGraph Orchestration for the Local Cowork Agent.

This module defines the state graph, nodes, and edges that control the agent's
reasoning loop, tool execution, and security validation. It supports switching
between 'reasoning' (agentic) and 'fast' (chat) modes.
"""

from langgraph.graph import StateGraph, START, END, MessagesState
from langgraph.checkpoint.redis.aio import AsyncRedisSaver
import redis
from langchain_core.messages import SystemMessage, AIMessage, ToolMessage, RemoveMessage, HumanMessage
from langgraph.prebuilt import ToolNode, tools_condition

from .state import AgentState
from .llm import get_small_llm, get_large_llm
from src.tools.core_tools import CORE_TOOLS
from src.tools.mcp_client import mcp_manager, get_mcp_tools
from src.memory.persona import get_persona, persona_to_system_prefix
from src.memory.user_profile import get_profile, profile_to_context
from src.memory.memory_manager import memories_to_context
from src.memory.project import project_manager
from src.memory.long_term import inject_context_node, extract_facts_node, analyze_memory_node
from src.config.settings import MCP_CONFIG_PATH, REDIS_URL
import logging

logger = logging.getLogger(__name__)

# Global instances
_agent_instance = None
_all_tools = []

import json
import re


async def small_llm_node(state: AgentState):
    """
    Orchestrator Node. Uses the Small LLM to route the logic flow.
    Outputs a structured JSON to decide the next path.
    """
    llm = get_small_llm()
    messages = state.get("messages", [])
    
    if not messages:
        return {"routing_decision": "SIMPLE"}

    # Get the last human message for analysis
    last_human = next(
        (m.content for m in reversed(messages) if hasattr(m, "type") and m.type == "human"), ""
    )
    
    # Suggestion #9: Keyword check to force CONTEXT for memory references
    memory_keywords = ["last time", "as before", "remember when", "we talked about", "you said"]
    force_context = any(kw in last_human.lower() for kw in memory_keywords) if isinstance(last_human, str) else False

    prompt = f"""
Analyze the user's input and determine the BEST routing action.
You MUST output EXACTLY ONE JSON block matching this format:

{{
  "routing": "SIMPLE | CONTEXT | TOOL | COMPLEX",
  "reason": "short explanation",
  "search_query": "formulate look up query if routing is CONTEXT, otherwise null",
  "confidence": 0.9
}}

Routing Criteria:
- SIMPLE: Greetings, casual chat, simple direct answers, thanking you.
- CONTEXT: Questions about the user's past, generic facts likely stored in documents/notes, or anything requiring memory lookup.
- TOOL: Read/write workspace files, execute shell command, sandboxed python.
- COMPLEX: Calculations, coding help, technical teaching, structured analysis, long research with synthesis.

USER INPUT: "{last_human}"

JSON RESPONSE:"""

    try:
        response = await llm.ainvoke([HumanMessage(content=prompt)])
        content = response.content.strip()
        
        # Robust JSON parsing
        match = re.search(r'\{.*\}', content, re.DOTALL)
        if match:
             parsed = json.loads(match.group(0))
             decision = parsed.get("routing", "COMPLEX").upper()
             confidence = parsed.get("confidence")
             search_query = parsed.get("search_query")
        else:
             parsed = {}
             decision = "COMPLEX"
             confidence = None
             search_query = None
             
        # Fallback/Sanitization
        if force_context:
             decision = "CONTEXT"
             logger.info("Forcing CONTEXT route due to memory keywords")
        elif decision not in ["SIMPLE", "CONTEXT", "TOOL", "COMPLEX"]:
             decision = "COMPLEX"
             
        # Suggestion #1 & #2: TOOL route goes to large_llm, skip manual tool_call creation

        return_state = {
            "routing_decision": decision,
            "current_task": parsed.get("reason", "Routing decision made"),
            "search_query": search_query if decision == "CONTEXT" else None,
            "routing_confidence": confidence
        }
             
        return return_state
        
    except Exception as e:
        print(f"Small LLM Routing Error: {e}")
        return {"routing_decision": "COMPLEX"}

async def simple_response_node(state: AgentState):
    """
    Generates a lightweight response using the Small LLM for simple queries.
    """
    llm = get_small_llm()
    messages = state.get("messages", [])
    
    system_prompt = "You are Owlynn, a friendly AI assistant. Answer the user response directly and concisely."
    
    # Simple prompt assembling
    structured_messages = [SystemMessage(content=system_prompt)] + messages
    
    response = await llm.ainvoke(structured_messages)
    return {"messages": [response]}



async def large_llm_node(state: AgentState):
    """
    The core reasoning engine of the agent. Uses the Large LLM to solve 
    complex tasks, synthesize information, and execute actions.
    """
    llm = get_large_llm()
    messages = state.get("messages", [])

    mode = state.get("mode", "tools_on")
    routing = state.get("routing_decision", "COMPLEX")

    # Treat as agentic if routed to TOOL or COMPLEX and tools are enabled
    agentic = routing in ["TOOL", "COMPLEX"] and mode != "tools_off"

    # --- 1. Static Rules (Persona, Guidelines, Project Instructions) ---
    try:
        persona = get_persona()
        persona_prefix = persona_to_system_prefix(persona)
    except Exception:
        persona_prefix = "You are Owlynn, a friendly AI study tutor and coding assistant.\n"

    # Project-specific instructions
    project_id = state.get("project_id", "default")
    project = project_manager.get_project(project_id)
    project_instructions = ""
    if project:
        project_instructions = f"\nPROJECT: {project['name']}\nPROJECT INSTRUCTIONS: {project['instructions']}\n"
    
    static_rules = persona_prefix + project_instructions + "\n"

    # No mode-specific restrictions here; persona holds the baseline.

    # Add agentic rules to static context
    if agentic:
        static_rules += """
You are a research assistant with tool access for files, code, and web search.
FAIR REPORTING: report facts on any topic objectively using search tools.
CORE RULES:
1. BE CONCISE: No preambles. Answer directly.
2. TOOL USAGE: Call tools to get facts. Max 4 calls per turn.
3. FILES: Access files using `list_workspace_files` and `read_workspace_file`.
4. REASONING: Wrap ALL thinking in ONE `<thought>` block. Keep it brief.
5. NO HALLUCINATION: If calling a tool, do NOT predict its output in the same message.
6. PRESENTATION: Avoid complex ASCII art with frame/box drawing characters. For grids, matrixes, or tables, strictly use Standard Markdown Tables or simple lists to stay fast.
7. WEB FALLBACK: If you have already read a file (or listed files) and the information is NOT in the local files, STOP reading more files. Instead, immediately call `web_search` with a clear, specific query. Do NOT re-read the same file or list files again. Local files → web search, not local files → more local files.
"""

    else:
        static_rules += "Answer concisely. No preambles.\n"

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

    # Only keep profile in system_content for prefix caching
    system_content = static_rules.strip()
    if profile_ctx.strip():
         system_content += "\n\n" + profile_ctx.strip()

    # --- 3. Assemble Messages ---
    context_limit = 10 
    all_non_system = [m for m in messages if not isinstance(m, SystemMessage)]
    
    # Slicing: Adjust backwards to ensure the list begins with a HumanMessage for template safety
    start_idx = max(0, len(all_non_system) - context_limit)
    while start_idx > 0 and not isinstance(all_non_system[start_idx], HumanMessage):
        start_idx -= 1
        
    recent_messages = all_non_system[start_idx:]

    structured_messages = [SystemMessage(content=system_content)]
    
    # Add history
    structured_messages += recent_messages
    
    # Inject retrieved turn-based context into the last message to preserve templates
    long_term_context = state.get("long_term_context")
    if mem_ctx or long_term_context:
        ctx_msg = "\n\n--- TURN CONTEXT & MEMORIES ---\n"
        if mem_ctx:
            ctx_msg += mem_ctx + "\n"
        if long_term_context:
            ctx_msg += long_term_context + "\n"
            
        if structured_messages:
            last_msg = structured_messages[-1]
            if hasattr(last_msg, "content") and isinstance(last_msg.content, str):
                # Recreate to avoid mutating history state by reference
                msg_type = type(last_msg)
                new_args = {"content": last_msg.content + ctx_msg}
                if hasattr(last_msg, "id"): new_args["id"] = last_msg.id
                if isinstance(last_msg, ToolMessage): new_args["tool_call_id"] = last_msg.tool_call_id
                if isinstance(last_msg, AIMessage): new_args["tool_calls"] = getattr(last_msg, "tool_calls", [])
                
                structured_messages[-1] = msg_type(**new_args)
            else:
                 structured_messages.append(SystemMessage(content=ctx_msg.strip()))

    # Bind tools with LLM only if tools are enabled
    if mode == "tools_off":
        llm_with_tools = llm
    else:
        # Re-fetch or use global
        global _all_tools
        if not _all_tools:
            _all_tools = CORE_TOOLS + get_mcp_tools()
        llm_with_tools = llm.bind_tools(_all_tools)
        
    # Async execution
    # Async execution with stop sequences for fast mode
    
    # DEBUG: Log prompt structure to diagnose LM Studio Jinja template error
    # DEBUG: Log prompt structure
    logger.debug(f"\n--- Turn Context ---\nMessages Count: {len(structured_messages)}")
    for i, m in enumerate(structured_messages):
        logger.debug(f"[{i}] Type: {type(m).__name__}, ID: {getattr(m, 'id', 'N/A')}")
            
    if mode == "tools_off":
        response = await llm_with_tools.ainvoke(
            structured_messages,
            stop=["I will", "Let me", "The user", "First,", "To answer"]
        )
    else:
        # Add stop sequences for tool loop prevention on local models
        response = await llm_with_tools.ainvoke(
            structured_messages,
            stop=['}, {', '}, \n{', '}]}, {"']
        )



    # Use robust parser for local models
    new_content = response.content
    new_tool_calls = response.tool_calls.copy() if response.tool_calls else []
    modified = False

    # Failsafe: Truncate output to remove "inner monologue" leaks or plan repetition
    if new_content:
        # 1. Handle cases where the model used tags (Robust Parsing)
        for tag_end in ["</thought>", "</think>"]:
            if tag_end in new_content:
                parts = new_content.split(tag_end, 1)
                new_content = parts[-1].strip()
                modified = True
                break
        
        for tag_start in ["<thought>", "<think>"]:
             if tag_start in new_content and "</" not in new_content:
                 new_content = new_content.split(tag_start)[0].strip()
                 modified = True
                 break

        new_content = re.sub(r'<(thought|think)>.*?</(thought|think)>', '', new_content, flags=re.DOTALL)

        # Removed monologue_patterns heuristic scraping (Static rule for old GLM-4 model)

        # Hard length limit for fast mode
        # Removed fast mode length restriction to allow detailed natural answers.

        # Removed manual JSON & XML parser fallbacks for old LLMs (legacy support)

    # Failsafe: Programmatic Refusal Override
    refusal_keywords = [
        "cannot engage in", "not able to provide information on", "political topics",
        "sensitive topics", "against my guidelines", "discuss political", "not equipped to"
    ]
    if mode != "tools_off" and new_content and any(k in new_content.lower() for k in refusal_keywords) and not new_tool_calls:
        already_searched = any(
            hasattr(m, 'type') and m.type == 'tool' and getattr(m, 'name', '') == 'web_search' 
            for m in messages[-3:]
        )
        if not already_searched:
            last_human = next((m.content for m in reversed(messages) if hasattr(m, "type") and m.type == "human"), "")
            if last_human:
                new_content = "" # Silence meta-refusal text
                new_tool_calls = [{
                    "name": "web_search",
                    "args": {"query": last_human, "news": True},
                    "id": f"call_forced_{len(messages)}"
                }]
                modified = True

    # --- File Loop Detector: force web_search if the AI keeps re-reading files with no result ---
    if mode != "tools_off" and not new_tool_calls:
        # Collect the last few tool messages to check for file-reading loops
        recent_tool_msgs = [
            m for m in messages[-8:]
            if hasattr(m, 'type') and m.type == 'tool'
        ]
        file_tool_names = {"read_workspace_file", "list_workspace_files", "search_workspace_files"}
        file_tool_calls = [
            m for m in recent_tool_msgs
            if getattr(m, 'name', '') in file_tool_names
        ]
        already_web_searched = any(
            getattr(m, 'name', '') == 'web_search' for m in recent_tool_msgs
        )

        if file_tool_calls and not already_web_searched:
            # Trigger 1: Any file read returned a thin/empty result (< 300 chars)
            thin_results = [
                m for m in file_tool_calls
                if isinstance(getattr(m, 'content', ''), str) and len(m.content.strip()) < 300
            ]
            # Trigger 2: The same file was read more than once (duplicate loop)
            read_args = [
                getattr(m, 'content', '') for m in file_tool_calls
                if getattr(m, 'name', '') == 'read_workspace_file'
            ]
            # Detect duplicate tool_call_ids or same content returned twice
            seen_contents = set()
            duplicate_reads = False
            for content in read_args:
                if content in seen_contents:
                    duplicate_reads = True
                    break
                seen_contents.add(content)

            should_fallback = len(thin_results) >= 1 or duplicate_reads

            if should_fallback:
                last_human = next(
                    (m.content for m in reversed(messages) if hasattr(m, "type") and m.type == "human"), ""
                )
                if last_human and isinstance(last_human, str):
                    logger.info("File loop detected — falling back to web_search")
                    new_content = ""
                    new_tool_calls = [{
                        "name": "web_search",
                        "args": {"query": last_human},
                        "id": f"call_webfallback_{len(messages)}"
                    }]
                    modified = True


    if new_content and new_tool_calls:
        # Removed aggressive pre-tool monologue stripping
        
        # If it still contains "Hello" or final-sounding answers while calling a tool, it's likely a hallucination/leak
        if len(new_content) < 150 and any(kw in new_content.lower() for kw in ["hello", "hi ", "based on", "here are", "i found"]):
             new_content = "" 
        modified = True

    if not new_content and not new_tool_calls:
        new_content = "Thinking..."
        modified = True

    if modified:
        response = AIMessage(
            content=new_content,
            tool_calls=new_tool_calls,
            id=response.id
        )

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
        return {}
        
    last_message = messages[-1]
    
    if hasattr(last_message, "tool_calls") and last_message.tool_calls:
        tool_messages = []
        danger_detected = False
        
        for tool_call in last_message.tool_calls:
            name = tool_call.get("name")
            args = tool_call.get("args", {})
            
            if name == "execute_sandboxed_shell":
                command = args.get("command", "")
                if command:
                    danger_patterns = ["rm -rf /", "rm -rf *", "mkfs", "dd if="]
                    if any(p in command for p in danger_patterns):
                        danger_detected = True
                        tool_messages.append(
                            ToolMessage(
                                tool_call_id=tool_call["id"],
                                name=name,
                                content=f"Security Exception: Command '{command}' was blocked. Execution denied."
                            )
                        )
                        continue
            
            if danger_detected:
                 tool_messages.append(
                    ToolMessage(
                        tool_call_id=tool_call["id"],
                        name=name,
                        content="Aborted due to security exception in sibling tool call."
                    )
                )
                 
        if danger_detected:
            retry_count = state.get("retry_count", 0) or 0
            return {"messages": tool_messages, "retry_count": retry_count + 1}
                        
    return {}

def validate_or_tools(state: AgentState):
    """Routes to tools if safe, or back to reasoning if blocked."""
    messages = state.get("messages", [])
    
    # Check retry budget for looped/blocked calls
    retry_count = state.get("retry_count", 0) or 0
    if retry_count >= 3:
        logger.warning("Validation retry limit reached. Breaking loop to analyze_memory.")
        return "analyze_memory"

    if messages and isinstance(messages[-1], ToolMessage):
        return "large_llm"
    
    # Use tools_condition to check for tool calls
    res = tools_condition(state)
    
    if res == END:
        return "analyze_memory"
    
    # Map 'tools' from tools_condition to 'tools' (same)
    # If tools_condition returns something else, verify.
    return res

async def summarize_history_node(state: AgentState):
    """
    Compresses conversation history if it exceeds a set limit to preserve memory overhead.
    """
    messages = state.get("messages", [])
    if len(messages) <= 20: 
        return {}
        
    recent_messages = messages[-10:]
    older_messages = [m for m in messages[:-10] if getattr(m, "type", "") != "system"]
    
    if not older_messages:
        return {}

    llm = get_small_llm()
    summary_prompt = (
        f"Summarize the following conversation history concisely. "
        f"Retain all factual data, file paths, and established constraints:\n\n"
        f"{older_messages}"
    )
    
    try:
        summary_response = await asyncio.wait_for(
            llm.ainvoke([HumanMessage(content=summary_prompt)]),
            timeout=20.0
        )
        summary_content = summary_response.content
    except asyncio.TimeoutError:
        logger.warning("summarize_history_node timed out. Proceeding without summary.")
        summary_content = "Previous conversation history collapsed due to processing timeout."
        
    summary_message = SystemMessage(content=f"Previous Conversation Summary: {summary_content}")
    
    # Instruct LangGraph to remove the older messages from the state
    delete_messages = [RemoveMessage(id=m.id) for m in older_messages if hasattr(m, "id") and m.id]
    
    return {"messages": delete_messages + [summary_message]}

def small_llm_routes(state: AgentState):
    """Routes from small_llm based on routing_decision."""
    return state.get("routing_decision", "COMPLEX")

def build_graph(tools):
    """
    Constructs the primary LangGraph execution structure.
    """
    workflow = StateGraph(AgentState)
    
    # Add nodes
    workflow.add_node("summarize", summarize_history_node)
    workflow.add_node("small_llm", small_llm_node)
    workflow.add_node("simple_response", simple_response_node)
    workflow.add_node("ltm_search", inject_context_node)
    workflow.add_node("large_llm", large_llm_node)
    workflow.add_node("validate", validate_node)
    workflow.add_node("tools", ToolNode(tools))
    workflow.add_node("analyze_memory", analyze_memory_node)
    workflow.add_node("extract_facts", extract_facts_node)
    
    # Define edges
    workflow.add_edge(START, "summarize")
    workflow.add_edge("summarize", "small_llm")
    
    # Route from Small LLM
    workflow.add_conditional_edges(
        "small_llm",
        small_llm_routes,
        {
            "SIMPLE": "simple_response",
            "CONTEXT": "ltm_search",
            "TOOL": "large_llm",  # Suggestion #1: TOOL route goes to large_llm
            "COMPLEX": "large_llm"
        }
    )
    
    # Connections after branching
    workflow.add_edge("simple_response", "analyze_memory")
    workflow.add_edge("ltm_search", "large_llm")
    workflow.add_edge("tools", "large_llm")
    
    # From Large LLM to validation
    workflow.add_edge("large_llm", "validate")
    
    # Validation loop (supports tools or ending)
    workflow.add_conditional_edges(
        "validate",
        validate_or_tools,
        {
            "tools": "tools", 
            "analyze_memory": "analyze_memory",
            "large_llm": "large_llm"
        }
    )
    
    # Connections after branching and validation loops are set
    workflow.add_edge("analyze_memory", "extract_facts")
    workflow.add_edge("extract_facts", END)

    return workflow


async def init_agent(checkpointer=None):
    """
    Initializes the compiled agent with memory check-pointing using Redis.

    This function compiles the StateGraph together with a Redis checkpointer
    for thread-level persistence.

    Args:
        checkpointer: Optional LangGraph checkpointer instance. If not provided,
                      a new AsyncRedisSaver will be initialized using REDIS_URL.

    Returns:
        The compiled LangGraph application.
    """
    # Initialize MCP tools
    await mcp_manager.initialize(str(MCP_CONFIG_PATH))
    global _all_tools
    _all_tools = CORE_TOOLS + get_mcp_tools()
    
    workflow = build_graph(_all_tools)
    
    # If no checkpointer is passed, we initialize one from REDIS_URL
    if checkpointer is None:
        # We initialize it natively to handle connection pooling.
        checkpointer = AsyncRedisSaver(redis_url=REDIS_URL)
        # Note: In an async context, we should ideally await checkpointer.asetup() 
        # and checkpointer.aset_client_info(), but compile() doesn't strictly 
        # require it to be initialized yet; however, for robustness we do it here.
        try:
            await checkpointer.asetup()
            await checkpointer.aset_client_info()
        except Exception as e:
            print(f"Warning: Failed to initialize Redis checkpointer: {e}")
            # Fallback to memory if Redis is unavailable
            from langgraph.checkpoint.memory import MemorySaver
            checkpointer = MemorySaver()
    
    # Compile the graph
    app = workflow.compile(checkpointer=checkpointer)
    return app
