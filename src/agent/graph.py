"""
LangGraph orchestration with a secure cyclic tool flow.
"""

from langgraph.graph import StateGraph, END
from src.agent.state import AgentState
from src.agent.nodes.router import router_node
from src.agent.nodes.simple import simple_node
from src.agent.nodes.complex import complex_llm_node, complex_tool_action_node
from src.agent.nodes.security_proxy import security_proxy_node
from src.agent.nodes.memory import memory_inject_node, memory_write_node
from src.agent.nodes.summarize import auto_summarize_node

import logging
logger = logging.getLogger(__name__)

# ── Summarize gate: conditional edge from memory_inject ───────────────

_DEFAULT_CONTEXT_WINDOW = 100_000
_SUMMARIZE_THRESHOLD = 0.85

def summarize_gate(state: AgentState) -> str:
    """Route to ``auto_summarize`` when active_tokens > 85% of context_window.

    Returns ``"auto_summarize"`` to trigger summarization, or ``"router"`` to skip.
    """
    active_tokens: int | None = state.get("active_tokens")
    context_window: int | None = state.get("context_window") or _DEFAULT_CONTEXT_WINDOW

    if not active_tokens or active_tokens <= 0:
        return "router"
    threshold = _SUMMARIZE_THRESHOLD * context_window
    if active_tokens > threshold:
        return "auto_summarize"
    return "router"

def route_decision(state: AgentState) -> str:
    route = state.get("route", "complex-default")
    if route == "simple":
        return "simple"
    # All complex-* routes map to the "complex_llm" node via the "complex" edge key.
    # The actual 5-way route value stays in AgentState for the complex node to read.
    valid_complex = {"complex-default", "complex-vision", "complex-longctx", "complex-cloud"}
    if route in valid_complex:
        return "complex"
    # Unrecognised route → default to complex
    return "complex"


def llm_next_step(state: AgentState) -> str:
    return "security_proxy" if bool(state.get("pending_tool_calls")) else "memory_write"


def security_next_step(state: AgentState) -> str:
    return "tool_action" if bool(state.get("execution_approved")) else "memory_write"


def build_graph():
    """
    Stateful cyclic LangGraph with mandatory security proxy before tool execution.

    Flow:
      memory_inject -> summarize_gate -> (if >85%) auto_summarize -> router -> ...
                                            (else) router -> ...
    """
    builder = StateGraph(AgentState)

    builder.add_node("memory_inject", memory_inject_node)
    builder.add_node("auto_summarize", auto_summarize_node)
    builder.add_node("router", router_node)
    builder.add_node("simple", simple_node)
    builder.add_node("complex_llm", complex_llm_node)
    builder.add_node("security_proxy", security_proxy_node)
    builder.add_node("tool_action", complex_tool_action_node)
    builder.add_node("memory_write", memory_write_node)

    builder.set_entry_point("memory_inject")

    # memory_inject -> summarize_gate -> [auto_summarize -> router] | [router]
    builder.add_conditional_edges("memory_inject", summarize_gate, {
        "auto_summarize": "auto_summarize",
        "router": "router",
    })
    builder.add_edge("auto_summarize", "router")

    builder.add_conditional_edges("router", route_decision, {
        "simple": "simple",
        "complex": "complex_llm",
    })

    builder.add_conditional_edges("complex_llm", llm_next_step, {
        "security_proxy": "security_proxy",
        "memory_write": "memory_write",
    })

    builder.add_conditional_edges("security_proxy", security_next_step, {
        "tool_action": "tool_action",
        "memory_write": "memory_write",
    })

    builder.add_edge("tool_action", "complex_llm")
    builder.add_edge("simple", "memory_write")
    builder.add_edge("memory_write", END)

    return builder

# --- Init Agent Async Wrapper ---
from langgraph.checkpoint.memory import MemorySaver
from src.config.settings import MCP_CONFIG_PATH, REDIS_URL
from src.tools.mcp_client import mcp_manager

async def init_agent(checkpointer=None):
    """Initializes the agent with Redis checkpointer (falls back to MemorySaver)."""
    try:
        await mcp_manager.initialize(str(MCP_CONFIG_PATH))
    except Exception:
        pass

    builder = build_graph()

    if checkpointer is None:
        try:
            from langgraph_checkpoint_redis import AsyncRedisSaver
            checkpointer = AsyncRedisSaver(url=REDIS_URL)
            await checkpointer.setup()
            logger.info("Using Redis checkpointer at %s", REDIS_URL)
        except Exception as e:
            logger.warning("Redis unavailable (%s), falling back to MemorySaver", e)
            checkpointer = MemorySaver()

    return builder.compile(checkpointer=checkpointer)
