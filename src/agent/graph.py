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

import logging
logger = logging.getLogger(__name__)

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
      memory_inject -> router -> simple -> memory_write -> END
                               complex_llm -> (if tool call) security_proxy
                               security_proxy -> tool_action -> complex_llm (loop)
                               complex_llm -> (if direct answer) memory_write -> END
    """
    builder = StateGraph(AgentState)

    builder.add_node("memory_inject", memory_inject_node)
    builder.add_node("router", router_node)
    builder.add_node("simple", simple_node)
    builder.add_node("complex_llm", complex_llm_node)
    builder.add_node("security_proxy", security_proxy_node)
    builder.add_node("tool_action", complex_tool_action_node)
    builder.add_node("memory_write", memory_write_node)

    builder.set_entry_point("memory_inject")
    builder.add_edge("memory_inject", "router")

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
