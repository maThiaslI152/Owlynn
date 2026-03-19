"""
Router Node - Optimized for M4
-------------------------------
Uses the Small LLM to quickly decide: simple response or complex reasoning.
Simplified from 4 routes to 2 for M4 efficiency.
"""

from langchain_core.messages import SystemMessage, HumanMessage, AIMessage
from src.agent.state import AgentState
from src.agent.llm import get_small_llm
import json
import re
import logging

logger = logging.getLogger(__name__)

# Streamlined router prompt for faster decisions on M4
ROUTER_PROMPT = """You are a routing expert. Analyze this message and decide:
- "simple": Greeting, casual chat, factual Q&A (just explain briefly)
- "complex": Needs reasoning, problem solving, writing, coding, calculations

Output ONLY this JSON format:
{{"routing": "simple" OR "complex", "confidence": 0.0-1.0}}

Message: "{user_input}"

JSON:"""

def parse_routing(content: str) -> str:
    """Extract routing decision from LLM response."""
    try:
        match = re.search(r'\{.*\}', content, re.DOTALL)
        if match:
            parsed = json.loads(match.group(0))
            decision = parsed.get("routing", "complex").lower().strip()
            if decision in ["simple", "complex"]:
                return decision
    except Exception:
        pass
    return "complex"  # Safe default (use large model if unsure)

async def router_node(state: AgentState) -> AgentState:
    """Route to simple or complex path based on quick analysis."""
    messages = state.get("messages", [])
    if not messages:
        return {"route": "complex"}
    
    user_input = messages[-1].content if messages else ""
    
    # Quick keyword check to bypass LLM for obvious cases (saves ~1s)
    simple_keywords = [
        "hello", "hi", "hey", "thanks", "thank you", "bye", "goodbye",
        "what time", "what date", "what's today", "weather"
    ]
    for kw in simple_keywords:
        if kw in user_input.lower():
            logger.info("[router] Simple path - keyword match")
            return {"route": "simple"}
    
    # Get small LLM (pooled instance - no reinit overhead)
    small_llm = await get_small_llm()
    
    try:
        response = await small_llm.ainvoke([
            SystemMessage(content=ROUTER_PROMPT.format(user_input=user_input[:200])),  # Limit input
        ])
        decision = parse_routing(response.content)
    except Exception as e:
        logger.error(f"[router] Error during routing: {e}")
        decision = "complex"  # Safe fallback
    
    logger.info(f"[router] → {decision}")
    return {"route": decision}
