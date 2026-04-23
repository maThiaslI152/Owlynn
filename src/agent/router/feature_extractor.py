"""
Feature extraction for the Multi-LLM Router.

Extracts structured TaskFeatures from user input and conversation state
to inform routing decisions. Pure function with no side effects on input state.
"""

from __future__ import annotations

import logging
from typing import Any

from src.agent.router.models import TaskFeatures
from src.config.settings import MEDIUM_DEFAULT_CONTEXT, MEDIUM_LONGCTX_CONTEXT

logger = logging.getLogger(__name__)

# ── Keyword lists (mirrored from router.py for feature scoring) ──────────

_WEBISH_HINTS = (
    "weather",
    "forecast",
    "temperature in",
    "humidity in",
    "stock price",
    "crypto price",
    "news ",
    "breaking",
    "search the web",
    "search for",
    "look up",
    "google ",
    "current price",
    "price in ",
    "price",
    "today's ",
    "right now",
    "live score",
)

_FRONTIER_HINTS = {
    "prove", "theorem", "formal proof", "mathematical proof",
    "symbolic", "calculus", "differential equation",
    "optimize algorithm", "complexity proof",
    "best possible", "highest quality", "frontier",
}

_DOC_KEYWORDS = (
    "summarize", "summary", "document", "paper", "article", "report",
    "analyze this", "long text", "pdf", "book", "chapter", "transcript",
)

_VISION_KEYWORDS = (
    "image", "picture", "photo", "screenshot", "diagram",
    "chart", "graph", "visual", "look at", "what do you see",
    "describe this", "ocr", "read the text in",
)

_CODE_KEYWORDS = ("code", "function", "debug", "implement", "refactor")

_ANALYSIS_KEYWORDS = ("analyze", "compare", "evaluate", "research")

_FILE_ATTACHMENT_HINTS = ("[file:", "uploaded to workspace", "workspace file")


# ── Helpers ──────────────────────────────────────────────────────────────

def _has_image_content(state: dict[str, Any]) -> bool:
    """Check if the last message contains image attachments."""
    messages = state.get("messages") or []
    if not messages:
        return False
    content = messages[-1].content
    if isinstance(content, list):
        return any(
            isinstance(block, dict) and block.get("type") == "image_url"
            for block in content
        )
    return False


def _last_user_text(state: dict[str, Any]) -> str:
    """Flatten last message content to plain text (handles string or multimodal list)."""
    messages = state.get("messages") or []
    if not messages:
        return ""
    raw = messages[-1].content
    if isinstance(raw, str):
        return raw
    if isinstance(raw, list):
        parts: list[str] = []
        for block in raw:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict):
                if block.get("type") == "text":
                    parts.append(str(block.get("text", "")))
        return "\n".join(parts) if parts else ""
    return str(raw)


def _needs_frontier_quality(text: str) -> bool:
    """Check if the task needs frontier-class model quality."""
    lower = text.lower()
    return any(hint in lower for hint in _FRONTIER_HINTS)


# ── Main extraction function ─────────────────────────────────────────────

def extract_features(user_text: str, state: dict[str, Any]) -> TaskFeatures:
    """
    Extract structured features from user input and conversation state.

    Preconditions:
    - user_text is a string (may be empty)
    - state is a dict with at least a ``messages`` key

    Postconditions:
    - Returns a valid TaskFeatures with all scores in range
    - No side effects on *state*

    On any unexpected error, returns conservative default TaskFeatures.
    """
    try:
        return _extract_features_inner(user_text, state)
    except Exception:
        logger.exception("[feature_extractor] Unexpected error — returning defaults")
        return _default_features()


def _default_features() -> TaskFeatures:
    """Return conservative default TaskFeatures (no images, general, zero scores)."""
    return TaskFeatures(
        has_images=False,
        has_file_attachments=False,
        estimated_input_tokens=4000,
        context_ratio_default=4000 / MEDIUM_DEFAULT_CONTEXT,
        context_ratio_longctx=4000 / MEDIUM_LONGCTX_CONTEXT,
        has_tool_history=False,
        web_intent=False,
        task_category="general",
        document_keywords_score=0.0,
        vision_keywords_score=0.0,
        frontier_quality_needed=False,
    )


def _extract_features_inner(user_text: str, state: dict[str, Any]) -> TaskFeatures:
    """Core extraction logic (may raise)."""
    text_lower = user_text.lower()
    messages = state.get("messages") or []

    # ── Image detection ──────────────────────────────────────────────
    has_images = _has_image_content(state)

    # ── File attachment detection ────────────────────────────────────
    has_files = any(hint in text_lower for hint in _FILE_ATTACHMENT_HINTS)

    # ── Token estimation ─────────────────────────────────────────────
    # ~4 chars ≈ 1 token, plus 4000 overhead for system prompt + context
    estimated_tokens = 4000 + (len(user_text) // 4)

    ratio_default = estimated_tokens / MEDIUM_DEFAULT_CONTEXT
    ratio_longctx = estimated_tokens / MEDIUM_LONGCTX_CONTEXT

    # ── Tool history ─────────────────────────────────────────────────
    has_tool_history = False
    if len(messages) > 2:
        has_tool_history = any(
            getattr(m, "type", None) == "tool"
            or (hasattr(m, "tool_calls") and m.tool_calls)
            for m in messages[:-1]
        )

    # ── Web intent ───────────────────────────────────────────────────
    web_intent = any(h in text_lower for h in _WEBISH_HINTS)

    # ── Document keyword scoring ─────────────────────────────────────
    doc_hits = sum(1 for kw in _DOC_KEYWORDS if kw in text_lower)
    doc_score = min(1.0, doc_hits / 3.0)

    # ── Vision keyword scoring ───────────────────────────────────────
    vision_hits = sum(1 for kw in _VISION_KEYWORDS if kw in text_lower)
    vision_score = min(1.0, vision_hits / 2.0)

    # ── Frontier quality detection ───────────────────────────────────
    frontier = _needs_frontier_quality(user_text)

    # ── Task category inference (priority: vision > document > code > analysis > general) ──
    if has_images or vision_score > 0.5:
        category = "vision"
    elif doc_score > 0.5 or ratio_default > 0.5:
        category = "document"
    elif any(kw in text_lower for kw in _CODE_KEYWORDS):
        category = "code"
    elif any(kw in text_lower for kw in _ANALYSIS_KEYWORDS):
        category = "analysis"
    else:
        category = "general"

    return TaskFeatures(
        has_images=has_images,
        has_file_attachments=has_files,
        estimated_input_tokens=estimated_tokens,
        context_ratio_default=ratio_default,
        context_ratio_longctx=ratio_longctx,
        has_tool_history=has_tool_history,
        web_intent=web_intent,
        task_category=category,
        document_keywords_score=doc_score,
        vision_keywords_score=vision_score,
        frontier_quality_needed=frontier,
    )
