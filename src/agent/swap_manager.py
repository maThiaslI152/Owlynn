"""
Swap Manager — wraps LM Studio native API for M-tier model load/unload.

Uses httpx.AsyncClient to communicate with the LM Studio management API
at ``/api/v1/models/*``.  Only one M-tier model may be loaded at a time
(VRAM constraint on Mac M4 Air 24 GB).
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

import httpx

from src.config.settings import M4_MAC_OPTIMIZATION
from src.memory.user_profile import get_profile

logger = logging.getLogger(__name__)


class ModelSwapError(Exception):
    """Raised when a model swap (unload → load → poll) fails."""


class SwapManager:
    """Manages hot-swapping of M-tier models via the LM Studio native API."""

    def __init__(self, base_url: str = "http://127.0.0.1:1234") -> None:
        self._base_url = base_url.rstrip("/")
        self._client = httpx.AsyncClient()
        self._current_variant: Optional[str] = None

    # ── public helpers ───────────────────────────────────────────────────

    def get_current_variant(self) -> str | None:
        """Return the currently loaded M-tier variant name, or *None*."""
        return self._current_variant

    async def get_loaded_instance_ids(self, model_key: str) -> list[str]:
        """Query ``GET /api/v1/models`` and return instance IDs for *model_key*."""
        try:
            resp = await self._client.get(
                f"{self._base_url}/api/v1/models", timeout=30
            )
            resp.raise_for_status()
            models = resp.json().get("models", [])
            for m in models:
                if m.get("key") == model_key:
                    return [inst["id"] for inst in m.get("loaded_instances", [])]
        except Exception as exc:
            logger.warning("Failed to query LM Studio models: %s", exc)
        return []

    # ── core swap logic ──────────────────────────────────────────────────

    async def swap_model(self, target_variant: str) -> None:
        """Unload the current M-tier model and load *target_variant*.

        Parameters
        ----------
        target_variant:
            One of ``"default"``, ``"vision"``, ``"longctx"``.

        Raises
        ------
        ModelSwapError
            If the target model does not appear in ``loaded_instances``
            within the configured timeout.
        """
        profile = get_profile()
        medium_models: dict = profile.get("medium_models", {})
        model_key = medium_models.get(target_variant)
        if not model_key:
            raise ModelSwapError(
                f"No model key configured for variant '{target_variant}' "
                f"in medium_models: {medium_models}"
            )

        swap_cfg = M4_MAC_OPTIMIZATION.get("medium_models", {})
        timeout: int = swap_cfg.get("swap_timeout", 120)
        poll_interval: int = swap_cfg.get("poll_interval", 2)

        # ── 1. Unload currently loaded M-tier instances ──────────────────
        await self._unload_current(medium_models)

        # ── 2. Load target model ─────────────────────────────────────────
        try:
            resp = await self._client.post(
                f"{self._base_url}/api/v1/models/load",
                json={"model": model_key},
                timeout=timeout,
            )
            if resp.status_code not in (200, 201, 202):
                logger.warning(
                    "Load request for %s returned %s: %s",
                    model_key, resp.status_code, resp.text[:300],
                )
        except Exception as exc:
            raise ModelSwapError(
                f"Load request failed for '{model_key}': {exc}"
            ) from exc

        # ── 3. Poll until target appears in loaded_instances ─────────────
        loaded = await self._poll_until_loaded(model_key, timeout, poll_interval)
        if not loaded:
            raise ModelSwapError(
                f"Model '{model_key}' did not appear in loaded_instances "
                f"within {timeout}s"
            )

        self._current_variant = target_variant
        logger.info("Swap complete → variant=%s  model=%s", target_variant, model_key)

    # ── private helpers ──────────────────────────────────────────────────

    async def _unload_current(self, medium_models: dict) -> None:
        """Best-effort unload of every loaded M-tier model instance."""
        for variant_key in medium_models.values():
            instance_ids = await self.get_loaded_instance_ids(variant_key)
            for inst_id in instance_ids:
                try:
                    resp = await self._client.post(
                        f"{self._base_url}/api/v1/models/unload",
                        json={"instance_id": inst_id},
                        timeout=30,
                    )
                    if resp.status_code not in (200, 204):
                        logger.warning(
                            "Unload instance %s returned %s: %s",
                            inst_id, resp.status_code, resp.text[:200],
                        )
                except Exception as exc:
                    logger.warning("Unload failed for instance %s: %s", inst_id, exc)

    async def _poll_until_loaded(
        self, model_key: str, timeout: int, poll_interval: int
    ) -> bool:
        """Return *True* once *model_key* has at least one loaded instance."""
        deadline = asyncio.get_event_loop().time() + timeout
        while asyncio.get_event_loop().time() < deadline:
            ids = await self.get_loaded_instance_ids(model_key)
            if ids:
                return True
            await asyncio.sleep(poll_interval)
        return False
