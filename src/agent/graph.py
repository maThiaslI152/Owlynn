"""
LangGraph Orchestration with Tool Selection Flow.
"""

from langgraph.graph import StateGraph, START, END
from src.agent.state import AgentState
from src.agent.nodes.router import router_node
from src.agent.nodes.simple import simple_node
from src.agent.nodes.complex import complex_node
from src.agent.nodes.tool_selector import tool_selector_node
from src.agent.nodes.tool_executor import tool_executor_node
from src.agent.nodes.memory import memory_inject_node, memory_write_node

import logging
logger = logging.getLogger(__name__)

def route_decision(state: AgentState) -> str:
    route = state.get("route", "complex")
    # Adapt routing logic to match suggestion
    valid = {"simple", "complex", "tool", "memory"}
    return route if route in valid else "complex"

def build_graph():
    builder = StateGraph(AgentState)
    
    # --- Register all nodes ---
    builder.add_node("memory_inject",  memory_inject_node)   # reads memory
    builder.add_node("router",         router_node)          # small model
    builder.add_node("simple",         simple_node)          # small model
    builder.add_node("complex",        complex_node)         # large model
    builder.add_node("tool_selector",  tool_selector_node)   # small model - NEW
    builder.add_node("tool_executor",  tool_executor_node)   # large model - NEW
    builder.add_node("memory_write",   memory_write_node)    # writes memory
    
    # --- Entry point ---
    builder.set_entry_point("memory_inject")
    
    # --- Linear: memory inject -> router ---
    builder.add_edge("memory_inject", "router")
    
    # --- Conditional branching from router ---
    builder.add_conditional_edges("router", route_decision, {
        "simple":  "simple",
        "complex": "complex",
        "tool":    "tool_selector",
        "memory":  "complex", # memory synthesis -> large model
    })
    
    # --- Tool path: selector -> executor ---
    builder.add_edge("tool_selector", "tool_executor")
    
    # --- All paths converge to memory_write ---
    builder.add_edge("simple",        "memory_write")
    builder.add_edge("complex",       "memory_write")
    builder.add_edge("tool_executor", "memory_write")
    builder.add_edge("memory_write", END)
    
    return builder

# --- Init Agent Async Wrapper ---
from langgraph.checkpoint.redis.aio import AsyncRedisSaver
from src.config.settings import MCP_CONFIG_PATH, REDIS_URL
from src.tools.mcp_client import mcp_manager

async def init_agent(checkpointer=None):
    """Initializes the agent with checkpointer."""
    try:
        await mcp_manager.initialize(str(MCP_CONFIG_PATH))
    except Exception:
         pass
         
    builder = build_graph()
    
    if checkpointer is None:
        checkpointer = AsyncRedisSaver(redis_url=REDIS_URL)
        try:
            await checkpointer.asetup()
            await checkpointer.aset_client_info()
        except Exception as e:
            print(f"Warning: Redis checkpointer failed: {e}")
            from langgraph.checkpoint.memory import MemorySaver
            checkpointer = MemorySaver()
            
    return builder.compile(checkpointer=checkpointer)
