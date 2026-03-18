"""
LLM Client Initialization.

This module provides helpers to initialize the LangChain ChatOpenAI client
configured to connect to a local MLX VLM server, loading settings from
the user profile.
"""

from langchain_openai import ChatOpenAI
from src.memory.user_profile import get_profile

def get_small_llm():
    """
    Initializes a ChatOpenAI client for the Small LLM (Orchestrator).
    """
    profile = get_profile()
    base_url = profile.get("small_llm_base_url", "http://127.0.0.1:1234/v1")
    model = profile.get("small_llm_model_name", "nvidia/nemotron-3-nano-4b")

    return ChatOpenAI(
        model=model, 
        api_key="sk-local-no-key-needed",
        base_url=base_url,
        temperature=0.3, # Lower temperature for better routing/logic
        max_tokens=2048,
        extra_body={"max_output_tokens": 2048}
    )

def get_large_llm():
    """
    Initializes a ChatOpenAI client for the Large LLM (Expert Reasoning).
    """
    profile = get_profile()
    base_url = profile.get("large_llm_base_url", "http://127.0.0.1:1234/v1")
    model = profile.get("large_llm_model_name", "qwen/qwen3.5-9b")

    return ChatOpenAI(
        model=model, 
        api_key="sk-local-no-key-needed",
        base_url=base_url,
        temperature=0.4,
        max_tokens=8192,
        extra_body={"max_output_tokens": 8192}
    )

def get_llm():
    """
    Backward compatibility alias. Returns the Large LLM.
    """
    return get_large_llm()

# --- TOP-LEVEL VARIABLES FOR SUGGESTION STRUCTURE ---
small_llm = get_small_llm()
large_llm = get_large_llm()

# --- TOOL BINDING FOR LARGE LLM ---
from src.tools import web_search, execute_python_code, read_workspace_file, recall_memories

TOOLS = [web_search, execute_python_code, read_workspace_file, recall_memories]
large_llm_with_tools = large_llm.bind_tools(TOOLS)

