"""
LLM Client Initialization.

This module provides helpers to initialize the LangChain ChatOpenAI client
configured to connect to a local MLX VLM server, loading settings from
the user profile.
"""

from langchain_openai import ChatOpenAI
from src.memory.user_profile import get_profile

def get_mlx_openai_client(model_name=None):
    """
    Initializes a ChatOpenAI client pointing to the local MLX server.

    Retrieves base URL and model name from the user profile, falling back
    to defaults if not set.

    Args:
        model_name (str, optional): Override the model name from profile.

    Returns:
        ChatOpenAI: Configured LangChain chat model.
    """
    profile = get_profile()
    
    # Use profile values if set, otherwise fall back to arguments/defaults
    base_url = profile.get("llm_base_url", "http://127.0.0.1:8080/v1")
    model = model_name or profile.get("llm_model_name", "qwen/qwen3.5-9b")

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
    Convenience wrapper for get_mlx_openai_client.
    """
    return get_mlx_openai_client()

