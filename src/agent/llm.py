"""
LLM Client Initialization with Instance Pooling for Mac M4 Optimization.

This module provides helpers to initialize the LangChain ChatOpenAI client
configured to connect to a local LM Studio server, with pooling to avoid
re-initialization overhead on Mac M4.

Three-slot pool: small (always loaded) + medium (swappable) + cloud (DeepSeek).
"""

import asyncio
import logging
from typing import Optional

from langchain_openai import ChatOpenAI

from src.config.settings import DEEPSEEK_API_KEY
from src.memory.user_profile import get_profile

logger = logging.getLogger(__name__)


class CloudUnavailableError(Exception):
    """Raised when no valid DeepSeek API key is configured."""


class LLMPool:
    """Singleton pool for LLM instances to avoid re-initialization overhead."""

    _small_llm: Optional[ChatOpenAI] = None
    _medium_llm: Optional[ChatOpenAI] = None
    _cloud_llm: Optional[ChatOpenAI] = None
    _current_medium_variant: Optional[str] = None
    _swap_manager: Optional["SwapManager"] = None  # noqa: F821 — forward ref
    _lock = asyncio.Lock()

    # ── small ────────────────────────────────────────────────────────────

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

    # ── medium (swappable local slot) ────────────────────────────────────

    @classmethod
    async def get_medium_llm(cls, variant: str = "default") -> ChatOpenAI:
        """Get or create cached medium LLM instance, swapping if needed.

        Parameters
        ----------
        variant:
            ``"default"`` | ``"vision"`` | ``"longctx"``

        Returns
        -------
        ChatOpenAI
            A LangChain client pointing at the now-loaded LM Studio model.
        """
        if cls._current_medium_variant == variant and cls._medium_llm is not None:
            return cls._medium_llm

        async with cls._lock:
            # Double-check after acquiring lock
            if cls._current_medium_variant == variant and cls._medium_llm is not None:
                return cls._medium_llm

            # Lazy-init swap manager
            if cls._swap_manager is None:
                from src.agent.swap_manager import SwapManager
                cls._swap_manager = SwapManager()

            await cls._swap_manager.swap_model(variant)

            profile = get_profile()
            medium_models: dict = profile.get("medium_models", {})
            model_name = medium_models.get(variant, "qwen/qwen3.5-9b")
            base_url = profile.get("llm_base_url", "http://127.0.0.1:1234/v1")

            cls._medium_llm = ChatOpenAI(
                model=model_name,
                api_key="sk-local-no-key-needed",
                base_url=base_url,
                temperature=0.4,
                max_tokens=4096,
                extra_body={"max_output_tokens": 4096},
            )
            cls._current_medium_variant = variant

        return cls._medium_llm

    # ── cloud (DeepSeek API) ─────────────────────────────────────────────

    @classmethod
    async def get_cloud_llm(cls) -> ChatOpenAI:
        """Get or create cached Cloud LLM (DeepSeek API) instance.

        Raises
        ------
        CloudUnavailableError
            If no valid API key is found in env var or profile.
        """
        if cls._cloud_llm is not None:
            return cls._cloud_llm

        async with cls._lock:
            if cls._cloud_llm is not None:
                return cls._cloud_llm

            api_key = cls._resolve_deepseek_api_key()
            if not api_key:
                raise CloudUnavailableError(
                    "No DeepSeek API key configured. Set DEEPSEEK_API_KEY env var "
                    "or deepseek_api_key in user profile."
                )

            profile = get_profile()
            base_url = profile.get("cloud_llm_base_url", "https://api.deepseek.com/v1")
            model = profile.get("cloud_llm_model_name", "deepseek-chat")

            cls._cloud_llm = ChatOpenAI(
                model=model,
                api_key=api_key,
                base_url=base_url,
                streaming=True,
                max_tokens=8192,
                temperature=0.4,
            )

        return cls._cloud_llm

    # ── backward-compat alias ────────────────────────────────────────────

    @classmethod
    async def get_large_llm(cls) -> ChatOpenAI:
        """Alias kept for backward compatibility during migration."""
        return await cls.get_medium_llm("default")

    # ── housekeeping ─────────────────────────────────────────────────────

    @classmethod
    def clear(cls):
        """Clear cached instances (call when profile updates)."""
        cls._small_llm = None
        cls._medium_llm = None
        cls._cloud_llm = None
        cls._current_medium_variant = None

    # ── private ──────────────────────────────────────────────────────────

    @staticmethod
    def _resolve_deepseek_api_key() -> str:
        """Env var → profile → empty string."""
        if DEEPSEEK_API_KEY:
            return DEEPSEEK_API_KEY
        profile = get_profile()
        profile_key = (profile.get("deepseek_api_key") or "").strip()
        return profile_key


# ── module-level convenience wrappers (unchanged API) ────────────────────

async def get_small_llm() -> ChatOpenAI:
    """Get small LLM instance (pooled for efficiency)."""
    return await LLMPool.get_small_llm()


async def get_large_llm() -> ChatOpenAI:
    """Get large LLM instance (pooled for efficiency)."""
    return await LLMPool.get_large_llm()


async def get_medium_llm(variant: str = "default") -> ChatOpenAI:
    """Get medium LLM instance (pooled, swaps if needed)."""
    return await LLMPool.get_medium_llm(variant)


async def get_cloud_llm() -> ChatOpenAI:
    """Get cloud LLM instance (DeepSeek API)."""
    return await LLMPool.get_cloud_llm()
