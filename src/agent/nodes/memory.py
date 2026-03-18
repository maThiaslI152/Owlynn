from langchain_core.messages import AIMessage
from src.agent.state import AgentState
from src.memory.memory_manager import save_memory, search_memories
from src.memory.user_profile import get_profile
from src.memory.persona import get_persona
import asyncio

# --- READ: fires before the brain node ---
async def memory_inject_node(state: AgentState) -> AgentState:
    thread_id    = state.get("thread_id", "default")
    user_message = state["messages"][-1].content if state.get("messages") else ""
    
    # Semantic search against long-term memory (mem0 instance falls back to dictionary/list setup in long_term.py)
    # We load it from long_term.py directly
    from src.memory.long_term import memory
    
    results = []
    if memory is not None:
         try:
              results_dict = await asyncio.to_thread(memory.search, user_message, user_id=thread_id, limit=5)
              results = results_dict.get("results", []) if isinstance(results_dict, dict) else results_dict
         except Exception:
              pass

    # Pull structured user profile
    profile = get_profile()

    # Pull persona summary
    persona = get_persona()

    # Format into a clean context block
    memory_context = format_memory_context(results, profile)
    return {
        "memory_context": memory_context,
        "persona": persona.get("role", "None")
    }

def format_memory_context(results: list, profile: dict) -> str:
    if not results and not profile:
         return "No prior memory available."
    lines = []
    if profile:
         lines.append("=== User Profile ===")
         for k, v in profile.items():
              if v:
                  lines.append(f"  {k}: {v}")
    if results:
         lines.append("=== Relevant Past Context ===")
         for item in results:
              # mem0 items usually have 'memory' key
              if isinstance(item, dict):
                  lines.append(f"  - {item.get('memory', item)}")
              else:
                   lines.append(f"  - {item}")
    return "\n".join(lines)

# --- WRITE: fires after response is generated ---
async def memory_write_node(state: AgentState) -> AgentState:
    thread_id = state.get("thread_id", "default")
    messages  = state.get("messages", [])
    
    last_human = next(
        (m.content for m in reversed(messages) if hasattr(m, "type") and m.type == "human"), None
    )
    last_ai = next(
        (m.content for m in reversed(messages) if hasattr(m, "type") and m.type == "ai"), None
    )
    
    if last_human and last_ai:
         from src.memory.long_term import memory
         if memory is not None:
              fact = f"User asked: {last_human}. AI answered: {last_ai}"
              try:
                   await asyncio.to_thread(memory.add, fact, user_id=thread_id, infer=True)
              except Exception:
                   pass
    return {}
