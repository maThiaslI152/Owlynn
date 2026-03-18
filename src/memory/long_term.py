"""
Long-Term Memory Management using Mem0 and ChromaDB.

This module initializes the Mem0 memory manager with a local ChromaDB instance
and defines graph nodes for injecting context and extracting facts.
"""

import os
import asyncio
import logging

logger = logging.getLogger(__name__)

# Mem0 implicitly initializes its internal default OpenAI client during setup,
# so we provide a dummy key to prevent `api_key` initialization errors,
# but we disable its automatic LLM calls below using `infer=False`.
os.environ["OPENAI_API_KEY"] = "sk-dummy-key"

from mem0 import Memory
from langchain_core.messages import SystemMessage, HumanMessage
from src.agent.state import AgentState

# To avoid circular imports, we import get_llm inside the node
async def analyze_memory_node(state: AgentState):
    """
    Analyzes the conversation history to extract important facts, user preferences,
    or key topics that should be remembered across sessions.
    """
    messages = state.get("messages", [])
    if not messages:
        return {}

    # DEBUG LOG Start
    logger.debug(f"\n>>> [Node] analyze_memory_node ENTERING\nMessages count: {len(messages)}")
    if messages:
        logger.debug(f"Last msg type: {messages[-1].type}")

    last_msg = messages[-1]
    if last_msg.type != "ai" or (hasattr(last_msg, "tool_calls") and last_msg.tool_calls):
        logger.debug(">>> [Node] analyze_memory_node SKIPPING: Not AI or has tool calls")
        return {}

    # Get the last couple of turns for context
    context = ""
    for m in messages[-4:]:
        role = "User" if m.type == "human" else "Assistant"
        content = m.content if isinstance(m.content, str) else "[Multimodal content]"
        context += f"{role}: {content}\n"

    # We need an LLM to extract facts.
    from src.agent.llm import get_small_llm
    llm = get_small_llm()

    prompt = f"""
Analyze the conversation below and extract any NEW important facts about the user, their preferences, 
projects, or specific keywords they want to track. 

Rules:
1. ONLY extract truly useful long-term facts (e.g., "User prefers Python over Java", "Project X is about AI", "User's favorite color is blue").
2. Do NOT extract temporary information or generic conversational filler.
3. Return the facts as a simple bulleted list.
4. If NO new facts are found, return the word "NONE".

CONVERSATION:
{context}

EXTRACTED FACTS:
"""
    try:
        response = await asyncio.wait_for(llm.ainvoke([HumanMessage(content=prompt)]), timeout=15.0)
        content = response.content.strip()
        
        if content == "NONE" or not content:
            return {}
            
        # Parse bullet points
        new_facts = []
        for line in content.split("\n"):
            line = line.strip().lstrip("-").lstrip("•").lstrip("*").strip()
            if line and len(line) > 5:
                new_facts.append(line)
        
        if new_facts:
            print(f"--- AUTO-EXTRACTED MEMORIES: {new_facts} ---")
            return {"extracted_facts": new_facts}
    except Exception as e:
        print(f"Memory Extraction Error: {e}")
        
    return {}


# Initialize Mem0 to use the local ChromaDB Podman instance we configured
config = {
    "vector_store": {
        "provider": "chroma",
        "config": {
            "host": "localhost",
            "port": 8000,
            "collection_name": "cowork_memory"
        }
    },
    # We will use our local Qwen2.5 via langchain proxy or an OpenAI-compatible endpoint 
    # if MLX Server is running. For now, mem0 natively supports openai format.
    # To keep it local without a server, we configure mem0 to use the local embedding model.
    "embedder": {
        "provider": "huggingface",
        "config": {
            "model": "BAAI/bge-small-en-v1.5"
        }
    }
}

try:
    memory = Memory.from_config(config)
except Exception as e:
    print(f"Warning: Failed to initialize Mem0/ChromaDB connection: {e}")
    memory = None

async def inject_context_node(state: AgentState):
    """
    RAG Pre-Execution Node.
    Takes the latest user message (or pre-formulated search_query) and searches Mem0/ChromaDB for relevant memories.
    Injects these memories into the `long_term_context` state variable before reasoning.
    """
    if memory is None:
        # Gracefully skip if ChromaDB is unavailable
        return {"long_term_context": ""}

    messages = state.get("messages", [])
    if not messages:
        return {}
        
    last_message = messages[-1]
    
    # We only inject context before reasoning on a *user* message
    if last_message.type != "human":
         return {}
         
    # Use pre-formulated search query if available, otherwise fallback to raw message
    query = state.get("search_query") or last_message.content
    project_id = state.get("project_id", "default")
    
    try:
        # Search long-term memory for relevance to the user's query
        # Use project_id for isolation
        # Wrap in asyncio.to_thread to prevent blocking the event loop
        results_dict = await asyncio.to_thread(memory.search, query, user_id=project_id, limit=3)
        
        context_str = ""
        results = results_dict.get("results", []) if isinstance(results_dict, dict) else results_dict
        if results:
            context_str = "Relevant facts from past sessions:\n"
            for r in results:
                context_str += f"- {r['memory']}\n"
                
        return {"long_term_context": context_str}
    except Exception as e:
        print(f"Memory Search Error: {e}")
        return {"long_term_context": ""}


async def extract_facts_node(state: AgentState):
    """
    Post-Execution Node.
    After a task finishes, this node looks at any facts the agent explicitly extracted 
    during its thread and permanently stores them in Mem0/ChromaDB.
    """
    if memory is None:
        return {}

    facts = state.get("extracted_facts", [])
    project_id = state.get("project_id", "default")
    
    if facts:
        try:
            # We explicitly pass infer=False because our local agent already handled the
            # intelligent extraction of facts; Mem0 just needs to store them directly.
            for fact in facts:
                await asyncio.to_thread(memory.add, fact, user_id=project_id, infer=False)
            
            # Optionally clear the thread facts now that they are in long-term storage
            # return {"extracted_facts": []} 
        except Exception as e:
             print(f"Memory Save Error: {e}")
    
    return {}
