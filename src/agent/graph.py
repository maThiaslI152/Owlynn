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
    """
    Optimized LangGraph for Mac M4 - streamlined routing with 2 main paths.
    Removes extra tool_selector node for faster execution.
    """
    builder = StateGraph(AgentState)
    
    # --- Register core nodes (simplified for M4 efficiency) ---
    builder.add_node("memory_inject", memory_inject_node)  # Enriches context
    builder.add_node("router",        router_node)         # Small model - decide path
    builder.add_node("simple",        simple_node)         # Small model - quick response
    builder.add_node("complex",       complex_node)        # Large model + tools when mode=tools_on
    builder.add_node("memory_write",  memory_write_node)   # Save to memory
    
    # --- Entry point ---
    builder.set_entry_point("memory_inject")
    
    # --- Linear: memory inject -> router ---
    builder.add_edge("memory_inject", "router")
    
    # --- Optimized conditional branching (2 paths instead of 4) ---
    builder.add_conditional_edges("router", route_decision, {
        "simple":  "simple",   # Quick responses via small model
        "complex": "complex",  # Deep reasoning + tools via large model
    })
    
    # --- All paths converge to memory_write for persistence ---
    builder.add_edge("simple",   "memory_write")
    builder.add_edge("complex",  "memory_write")
    builder.add_edge("memory_write", END)
    
    return builder

# --- Init Agent Async Wrapper ---
from langgraph.checkpoint.memory import MemorySaver  # Optimized for M4
from src.config.settings import MCP_CONFIG_PATH, REDIS_URL
from src.tools.mcp_client import mcp_manager
import logging

logger = logging.getLogger(__name__)

async def init_agent(checkpointer=None):
    """Initializes the agent with optimized checkpointer for Mac M4."""
    try:
        await mcp_manager.initialize(str(MCP_CONFIG_PATH))
    except Exception:
        pass
    
    # Initialize LLM pool on startup (one-time cache population)
    try:
        from src.agent.llm import initialize_llm_pool
        await initialize_llm_pool()
        logger.info("[init_agent] LLM pool initialized")
    except Exception as e:
        logger.warning(f"[init_agent] LLM pool init failed: {e}")
    
    builder = build_graph()
    
    if checkpointer is None:
        # Use MemorySaver for M4 Air (more efficient than Redis)
        # Falls back from Redis automatically if needed
        try:
            from langgraph.checkpoint.redis.aio import AsyncRedisSaver
            checkpointer = AsyncRedisSaver(redis_url=REDIS_URL)
            await checkpointer.asetup()
            logger.info("[init_agent] Using Redis checkpointer")
        except Exception as redis_err:
            logger.warning(f"[init_agent] Redis unavailable: {redis_err}, using MemorySaver")
            checkpointer = MemorySaver()
            
    return builder.compile(checkpointer=checkpointer)
