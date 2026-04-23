"""
Swap-aware route selector for the Multi-LLM Router.

Makes the final routing decision, factoring in the currently-loaded model
variant to avoid unnecessary swaps on VRAM-constrained hardware.
"""

from __future__ import annotations

import logging

from src.agent.router.models import RouteClassification, TaskFeatures

logger = logging.getLogger(__name__)


def _route_to_variant(route: str) -> str | None:
    """Map a route string to the corresponding M-tier variant name.

    Returns ``None`` for routes that don't map to an M-tier variant
    (e.g. ``"simple"`` or ``"complex-cloud"``).
    """
    mapping = {
        "complex-default": "default",
        "complex-vision": "vision",
        "complex-longctx": "longctx",
    }
    return mapping.get(route)


def _check_cloud_available() -> bool:
    """Check if cloud escalation is possible (API key + enabled).

    Called fresh on every request — intentionally not cached so that
    cloud availability is re-evaluated each time (Requirement 6.3).
    """
    try:
        from src.memory.user_profile import get_profile
        from src.agent.llm import LLMPool

        profile = get_profile()
        if not profile.get("cloud_escalation_enabled", True):
            return False
        api_key = LLMPool._resolve_deepseek_api_key()
        return bool(api_key)
    except Exception:
        return False


class RouteSelector:
    """Swap-aware route selector.

    Decides whether to keep the currently-loaded M-tier variant or swap
    to the classified target, based on confidence and task compatibility.
    """

    def select(
        self,
        classification: RouteClassification,
        features: TaskFeatures,
        current_variant: str | None,
        swap_threshold: float = 0.7,
    ) -> tuple[str, list[str]]:
        """Return ``(final_route, toolbox)`` with swap-avoidance logic.

        Preconditions:
        - ``classification.route`` is a valid route string
        - ``classification.confidence`` in ``[0.0, 1.0]``
        - ``current_variant`` is ``None``, ``"default"``, ``"vision"``, or ``"longctx"``

        Postconditions:
        - Returns ``(route, toolbox)`` where route is a valid route string
        - ``"simple"`` and ``"complex-cloud"`` routes pass through unchanged
        - If target variant matches current variant, classified route returned unchanged
        - If confidence < swap_threshold and current variant can handle the task,
          route maps to current variant (no swap triggered)
        - If confidence >= swap_threshold, route matches classification.route
        """
        target_route = classification.route
        toolbox = classification.toolbox

        # Simple route — no swap consideration needed
        if target_route == "simple":
            return target_route, toolbox

        # Cloud route — separate infrastructure, no M-tier swap
        if target_route == "complex-cloud":
            return target_route, toolbox

        target_variant = _route_to_variant(target_route)

        # Target is already loaded — no swap needed
        if target_variant == current_variant:
            return target_route, toolbox

        # Swap-avoidance: low confidence + current variant is viable
        if classification.confidence < swap_threshold:
            kept = self._try_keep_current(current_variant, features)
            if kept is not None:
                logger.info(
                    "[selector] Swap avoided: confidence=%.2f < threshold=%.2f, "
                    "keeping %s",
                    classification.confidence,
                    swap_threshold,
                    kept,
                )
                return kept, toolbox

        # High confidence or current variant can't handle it — proceed with swap
        return target_route, toolbox

    # ── Private helpers ──────────────────────────────────────────────

    @staticmethod
    def _try_keep_current(
        current_variant: str | None,
        features: TaskFeatures,
    ) -> str | None:
        """Return a route string if the current variant can handle the task.

        Returns ``None`` if the current variant is not viable and a swap
        should proceed.
        """
        if current_variant == "default":
            # Default can handle non-vision tasks that fit its context window
            if not features.has_images and features.context_ratio_default < 0.80:
                return "complex-default"

        elif current_variant == "longctx":
            # Longctx can handle general (non-vision) tasks
            if not features.has_images:
                return "complex-longctx"

        elif current_variant == "vision":
            # Vision model is less general — only keep if task has visual elements
            if features.vision_keywords_score > 0.3:
                return "complex-vision"

        return None

    @staticmethod
    def _downgrade_cloud_route(features: TaskFeatures) -> str:
        """Downgrade a cloud route to a local variant.

        If estimated input exceeds 80% of Medium_Default context, use longctx;
        otherwise fall back to default.
        """
        if features.context_ratio_default > 0.80:
            logger.warning(
                "[selector] Cloud unavailable, downgrading to complex-longctx"
            )
            return "complex-longctx"
        logger.warning(
            "[selector] Cloud unavailable, downgrading to complex-default"
        )
        return "complex-default"
