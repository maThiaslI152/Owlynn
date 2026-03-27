"""
LLM Client Initialization with Instance Pooling for Mac M4 Optimization.

This module provides helpers to initialize the LangChain ChatOpenAI client
configured to connect to a local LM Studio server, with pooling to avoid
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
            try:
                async with cls._lock:
                    if cls._small_llm is None:
                        profile = get_profile()
                        base_url = profile.get("small_llm_base_url", "http://127.0.0.1:1234/v1")
                        model = profile.get("small_llm_model_name", "liquid/lfm2.5-1.2b")
                        cls._small_llm = ChatOpenAI(
                            model=model,
                            api_key="sk-local-no-key-needed",
                            base_url=base_url,
                            temperature=0.2,
                            max_tokens=512,
                            extra_body={"max_output_tokens": 512},
                        )
            except Exception:
                profile = get_profile()
                base_url = profile.get("small_llm_base_url", "http://127.0.0.1:1234/v1")
                model = profile.get("small_llm_model_name", "liquid/lfm2.5-1.2b")
                return ChatOpenAI(
                    model=model,
                    api_key="sk-local-no-key-needed",
                    base_url=base_url,
                    temperature=0.2,
                    max_tokens=512,
                    extra_body={"max_output_tokens": 512},
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
                            max_tokens=4096,
                            extra_body={"max_output_tokens": 4096},
                        )
            except Exception:
                profile = get_profile()
                base_url = profile.get("large_llm_base_url", "http://127.0.0.1:1234/v1")
                model = profile.get("large_llm_model_name", "qwen/qwen3.5-9b")
                return ChatOpenAI(
                    model=model,
                    api_key="sk-local-no-key-needed",
                    base_url=base_url,
                    temperature=0.4,
                    max_tokens=4096,
                    extra_body={"max_output_tokens": 4096},
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


