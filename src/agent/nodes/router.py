"""
Router Node
-----------
Uses the Small LLM to decide the next path: simple, complex, tool, or memory.
"""

from langchain_core.messages import SystemMessage, HumanMessage, AIMessage
from src.agent.state import AgentState
from src.agent.llm import small_llm
import json
import re
import logging

logger = logging.getLogger(__name__)

ROUTER_PROMPT = """
Analyze the user's input and determine the BEST routing action.
You MUST output EXACTLY ONE JSON block matching this format:

{{
  "routing": "simple | complex | tool | memory",
  "reason": "short explanation",
  "confidence": 0.9
}}

Routing Criteria:
- simple: Greetings, casual chat, thanking you, or simple direct questions.
- memory: Questions explicitly asking about PAST conversations, user preferences, or self-recollection.
- tool: File manipulation (read/write), executing shell commands, or running python code.
- complex: Everything else requiring deep reasoning, calculations, coding help, or multi-step synthesis.

USER INPUT: "{user_input}"

JSON RESPONSE:"""

def parse_routing(content: str) -> str:
    try:
        match = re.search(r'\{.*\}', content, re.DOTALL)
        if match:
             parsed = json.loads(match.group(0))
             decision = parsed.get("routing", "complex").lower().strip()
             if decision in ["simple", "complex", "tool", "memory"]:
                 return decision
    except Exception:
         pass
    return "complex"  # Safe default

async def router_node(state: AgentState) -> AgentState:
    messages = state.get("messages", [])
    user_input = messages[-1].content if messages else ""
    
    # Keyword check fallback for forcing memory/context routing
    memory_keywords = ["last time", "as before", "remember when", "we talked about", "you said"]
    force_memory = any(kw in str(user_input).lower() for kw in memory_keywords)

    if force_memory:
         state["route"] = "memory"
         logger.info("[router] → Forcing memory route due to keywords")
         return state

    response = await small_llm.ainvoke([
        SystemMessage(content=ROUTER_PROMPT.format(user_input=user_input)),
    ])
    
    decision = parse_routing(response.content)
    print(f"[router] → {decision}")
    return {"route": decision}
