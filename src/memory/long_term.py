"""
Long-Term Memory Management using Mem0 and ChromaDB.

This module initializes the Mem0 memory manager with a local ChromaDB instance
and defines graph nodes for injecting context and extracting facts.
"""

import os

# Mem0 implicitly initializes its internal default OpenAI client during setup,
# so we provide a dummy key to prevent `api_key` initialization errors,
# but we disable its automatic LLM calls below using `infer=False`.
os.environ["OPENAI_API_KEY"] = "sk-dummy-key"

from mem0 import Memory
from src.agent.state import AgentState

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

memory = Memory.from_config(config)

def inject_context_node(state: AgentState):
    """
    RAG Pre-Execution Node.
    Takes the latest user message and searches Mem0/ChromaDB for relevant memories.
    Injects these memories into the `long_term_context` state variable before reasoning.
    """
    messages = state.get("messages", [])
    if not messages:
        return {}
        
    last_message = messages[-1]
    
    # We only inject context before reasoning on a *user* message
    if last_message.type != "human":
         return {}
         
    query = last_message.content
    
    try:
        # Search long-term memory for relevance to the user's query
        results_dict = memory.search(query, user_id="local_user", limit=3)
        
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


def extract_facts_node(state: AgentState):
    """
    Post-Execution Node.
    After a task finishes, this node looks at any facts the agent explicitly extracted 
    during its thread and permanently stores them in Mem0/ChromaDB.
    """
    facts = state.get("extracted_facts", [])
    
    if facts:
        try:
            # We explicitly pass infer=False because our local agent already handled the
            # intelligent extraction of facts; Mem0 just needs to store them directly.
            for fact in facts:
                memory.add(fact, user_id="local_user", infer=False)
            
            # Optionally clear the thread facts now that they are in long-term storage
            # return {"extracted_facts": []} 
        except Exception as e:
             print(f"Memory Save Error: {e}")
    
    return {}
