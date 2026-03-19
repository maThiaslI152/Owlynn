"""
LLM Client Initialization with Instance Pooling for Mac M4 Optimization.

This module provides helpers to initialize the LangChain ChatOpenAI client
configured to connect to a local MLX VLM server, with pooling to avoid
re-initialization overhead on Mac M4.
"""

from langchain_openai import ChatOpenAI
from src.memory.user_profile import get_profile
from typing import Optional
import asyncio

class LLMPool:
    """Singleton pool for LLM instances to avoid re-initialization overhead."""
    _small_llm: Optional[ChatOpenAI] = None
    _large_llm: Optional[ChatOpenAI] = None
    _lock = asyncio.Lock()
    
    @classmethod
    async def get_small_llm(cls) -> ChatOpenAI:
        """Get or create cached small LLM instance."""
        if cls._small_llm is None:
            # Avoid race condition with double-check locking
            try:
                async with cls._lock:
                    if cls._small_llm is None:
                        profile = get_profile()
                        base_url = profile.get("small_llm_base_url", "http://127.0.0.1:1234/v1")
                        model = profile.get("small_llm_model_name", "nvidia/nemotron-3-nano-4b")
                        
                        cls._small_llm = ChatOpenAI(
                            model=model,
                            api_key="sk-local-no-key-needed",
                            base_url=base_url,
                            temperature=0.3,  # Lower for routing accuracy
                            max_tokens=1024,  # Optimized for M4 (routing doesn't need 2048)
                            extra_body={"max_output_tokens": 1024}
                        )
            except Exception:
                # Fallback: create non-pooled instance
                profile = get_profile()
                base_url = profile.get("small_llm_base_url", "http://127.0.0.1:1234/v1")
                model = profile.get("small_llm_model_name", "nvidia/nemotron-3-nano-4b")
                return ChatOpenAI(
                    model=model,
                    api_key="sk-local-no-key-needed",
                    base_url=base_url,
                    temperature=0.3,
                    max_tokens=1024,
                    extra_body={"max_output_tokens": 1024}
                )
        return cls._small_llm
    
    @classmethod
    async def get_large_llm(cls) -> ChatOpenAI:
        """Get or create cached large LLM instance."""
        if cls._large_llm is None:
            try:
                async with cls._lock:
                    if cls._large_llm is None:
                        profile = get_profile()
                        base_url = profile.get("large_llm_base_url", "http://127.0.0.1:1234/v1")
                        model = profile.get("large_llm_model_name", "qwen/qwen3.5-9b")
                        
                        cls._large_llm = ChatOpenAI(
                            model=model,
                            api_key="sk-local-no-key-needed",
                            base_url=base_url,
                            temperature=0.4,
                            max_tokens=4096,  # Reduced from 8192 for M4 efficiency
                            extra_body={"max_output_tokens": 4096}
                        )
            except Exception:
                # Fallback: create non-pooled instance
                profile = get_profile()
                base_url = profile.get("large_llm_base_url", "http://127.0.0.1:1234/v1")
                model = profile.get("large_llm_model_name", "qwen/qwen3.5-9b")
                return ChatOpenAI(
                    model=model,
                    api_key="sk-local-no-key-needed",
                    base_url=base_url,
                    temperature=0.4,
                    max_tokens=4096,
                    extra_body={"max_output_tokens": 4096}
                )
        return cls._large_llm
    
    @classmethod
    def clear(cls):
        """Clear cached instances (call when profile updates)."""
        cls._small_llm = None
        cls._large_llm = None

async def get_small_llm() -> ChatOpenAI:
    """Get small LLM instance (pooled for efficiency)."""
    return await LLMPool.get_small_llm()

async def get_large_llm() -> ChatOpenAI:
    """Get large LLM instance (pooled for efficiency)."""
    return await LLMPool.get_large_llm()

def get_llm():
    """
    Backward compatibility alias. Returns the Large LLM (sync wrapper).
    """
    # For sync contexts, return non-pooled instance
    profile = get_profile()
    base_url = profile.get("large_llm_base_url", "http://127.0.0.1:1234/v1")
    model = profile.get("large_llm_model_name", "qwen/qwen3.5-9b")
    return ChatOpenAI(
        model=model,
        api_key="sk-local-no-key-needed",
        base_url=base_url,
        temperature=0.4,
        max_tokens=4096,
        extra_body={"max_output_tokens": 4096}
    )

# --- TOP-LEVEL VARIABLES FOR LEGACY CODE - Initialize lazily ---
small_llm = None
large_llm = None

async def initialize_llm_pool():
    """Initialize LLM pool on startup (call from async context)."""
    global small_llm, large_llm
    small_llm = await LLMPool.get_small_llm()
    large_llm = await LLMPool.get_large_llm()
    return small_llm, large_llm

# --- TOOL BINDING FOR LARGE LLM ---
from src.tools import web_search, execute_python_code, read_workspace_file, recall_memories

TOOLS = [web_search, execute_python_code, read_workspace_file, recall_memories]
async def get_large_llm_with_tools():
    """Returns the large LLM with tools bound."""
    llm = await LLMPool.get_large_llm()
    return llm.bind_tools(TOOLS)


