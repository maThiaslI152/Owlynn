from langchain_core.messages import AIMessage
from src.agent.state import AgentState
from src.memory.memory_manager import save_memory, search_memories
from src.memory.user_profile import get_profile
from src.memory.persona import get_persona
import asyncio
from datetime import datetime, timedelta
from typing import Optional

# Import enhanced personal assistant memory system
from src.memory.personal_assistant import (
    TopicExtractor, ConversationSummary, MemoryEnricher,
    record_conversation, get_memory_context_for_prompt,
    get_relevant_topics, get_user_interests_summary
)

# --- M4 OPTIMIZATION: Memory Context Cache ---
class MemoryContextCache:
    """Cache memory context to avoid rebuilding for every request."""
    _cache = {}
    _ttl_seconds = 300  # 5 minute cache
    
    @classmethod
    def get(cls, thread_id: str) -> Optional[str]:
        """Get cached context if still valid."""
        if thread_id in cls._cache:
            cached_at, context = cls._cache[thread_id]
            age = datetime.now() - cached_at
            if age < timedelta(seconds=cls._ttl_seconds):
                return context
            else:
                del cls._cache[thread_id]
        return None
    
    @classmethod
    def set(cls, thread_id: str, context: str):
        """Cache context with timestamp."""
        cls._cache[thread_id] = (datetime.now(), context)
    
    @classmethod
    def invalidate(cls, thread_id: str):
        """Invalidate cache when memory updates."""
        if thread_id in cls._cache:
            del cls._cache[thread_id]
    
    @classmethod
    def clear_old(cls):
        """Remove expired cache entries."""
        now = datetime.now()
        expired = [k for k, (t, _) in cls._cache.items() 
                   if now - t > timedelta(seconds=cls._ttl_seconds)]
        for k in expired:
            del cls._cache[k]

# --- READ: fires before the brain node ---
async def memory_inject_node(state: AgentState) -> AgentState:
    thread_id    = state.get("thread_id", "default")
    user_message = state["messages"][-1].content if state.get("messages") else ""
    
    # Check cache first (M4 optimization - avoid rebuilding context repeatedly)
    cached_context = MemoryContextCache.get(thread_id)
    if cached_context:
        persona = get_persona()
        return {
            "memory_context": cached_context,
            "persona": persona.get("role", "None")
        }
    
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
    
    # Get enhanced memory context with topics and interests
    enhanced_context = get_memory_context_for_prompt()

    # Get active project instructions (if in a project context)
    project_instructions = ""
    project_id = state.get("project_id")
    if project_id and project_id != "default":
        try:
            from src.memory.project import project_manager
            project = project_manager.get_project(project_id)
            if project and project.get("instructions"):
                project_instructions = project["instructions"]
        except Exception:
            pass

    # Format into a clean context block
    memory_context = format_memory_context(results, profile, enhanced_context, project_instructions)
    
    # Cache for subsequent requests (M4 optimization)
    MemoryContextCache.set(thread_id, memory_context)
    
    return {
        "memory_context": memory_context,
        "persona": persona.get("role", "None")
    }

def format_memory_context(results: list, profile: dict, enhanced_context: str = "", project_instructions: str = "") -> str:
    """Format memory context with profile, relevant memories, enriched personal knowledge, and project instructions."""
    lines = []

    # Add project instructions first (highest priority context)
    if project_instructions:
        lines.append("=== Project Instructions ===")
        lines.append(project_instructions)
    
    # Add enhanced memory context (topics, interests, recent convos)
    if enhanced_context:
        lines.append("=== Your Knowledge About User ===")
        lines.append(enhanced_context)
    
    # Add user profile (only human-relevant fields, not config)
    _PROFILE_SKIP = {
        'system_prompt', 'custom_instructions', 'llm_base_url', 'llm_model_name',
        'small_llm_base_url', 'small_llm_model_name', 'large_llm_base_url', 'large_llm_model_name',
        'temperature', 'top_p', 'max_tokens', 'top_k', 'streaming_enabled',
        'show_thinking', 'show_tool_execution', 'lm_studio_fold_system',
        'short_term_enabled', 'long_term_enabled', 'domains_of_interest',
    }
    if profile:
         lines.append("\n=== User Profile ===")
         for k, v in profile.items():
              if v and k not in _PROFILE_SKIP:
                  lines.append(f"  {k}: {v}")
    
    # Add relevant past context
    if results:
         lines.append("\n=== Relevant Past Context ===")
         for item in results:
              if isinstance(item, dict):
                  lines.append(f"  - {item.get('memory', item)}")
              else:
                   lines.append(f"  - {item}")
    
    return "\n".join(lines) if lines else "No prior memory available."

# --- WRITE: fires after response is generated ---
async def memory_write_node(state: AgentState) -> AgentState:
    """Extract and save memories, topics, and interests from conversation."""
    thread_id = state.get("thread_id", "default")
    messages  = state.get("messages", [])
    session_id = state.get("session_id", thread_id)
    
    if not messages:
        return {}
    
    # Extract last human and AI messages
    last_human = next(
        (m.content for m in reversed(messages) if hasattr(m, "type") and m.type == "human"), None
    )
    last_ai = next(
        (m.content for m in reversed(messages) if hasattr(m, "type") and m.type == "ai"), None
    )
    
    if not (last_human and last_ai):
        return {}
    
    # Record this turn in conversation
    try:
        # Convert messages to dict format
        message_dicts = []
        for msg in messages:
            if hasattr(msg, "type"):
                role = "user" if msg.type == "human" else "assistant"
            else:
                role = msg.get("role", "user")
            
            content = msg.content if hasattr(msg, "content") else msg.get("content", "")
            message_dicts.append({"role": role, "content": content})
        
        # Record conversation and extract topics/interests
        await asyncio.to_thread(record_conversation, message_dicts, session_id)
        
    except Exception as e:
        print(f"[Memory] Failed to record conversation: {e}")
    
    # Save enriched facts to long-term memory
    from src.memory.long_term import memory
    if memory is not None:
        try:
            # Extract topics and interests from the conversation
            conversation_text = f"{last_human} {last_ai}"
            topics = TopicExtractor.extract_topics(conversation_text)
            interests = TopicExtractor.extract_interests(conversation_text)
            
            # Create enriched fact
            fact_text = f"User asked: {last_human}. AI answered: {last_ai}"
            enriched_fact = MemoryEnricher.enrich_memory(fact_text, topics, interests)
            
            # Save to Mem0 with enriched metadata
            await asyncio.to_thread(
                memory.add, 
                fact_text, 
                user_id=thread_id, 
                infer=True
            )
            
            # Invalidate memory context cache since memory was updated (M4 optimization)
            MemoryContextCache.invalidate(thread_id)
            
        except Exception as e:
            print(f"[Memory] Failed to save enriched memory: {e}")
    
    return {}

