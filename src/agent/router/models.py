"""
Data models for the Multi-LLM Router.

Defines TaskFeatures, RouteClassification, and RouterConfig dataclasses
with __post_init__ validation.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# ── Valid enumerations ───────────────────────────────────────────────────

VALID_TASK_CATEGORIES = frozenset({"general", "document", "vision", "code", "analysis"})

VALID_ROUTES = frozenset({
    "simple",
    "complex-default",
    "complex-vision",
    "complex-longctx",
    "complex-cloud",
})


# ── TaskFeatures ─────────────────────────────────────────────────────────

@dataclass
class TaskFeatures:
    """Structured features extracted from user input and conversation state."""

    has_images: bool
    has_file_attachments: bool
    estimated_input_tokens: int
    context_ratio_default: float
    context_ratio_longctx: float
    has_tool_history: bool
    web_intent: bool
    task_category: str
    document_keywords_score: float
    vision_keywords_score: float
    frontier_quality_needed: bool

    def __post_init__(self) -> None:
        if self.estimated_input_tokens < 0:
            raise ValueError(
                f"estimated_input_tokens must be non-negative, got {self.estimated_input_tokens}"
            )

        if self.document_keywords_score < 0.0 or self.document_keywords_score > 1.0:
            raise ValueError(
                f"document_keywords_score must be in [0.0, 1.0], got {self.document_keywords_score}"
            )

        if self.vision_keywords_score < 0.0 or self.vision_keywords_score > 1.0:
            raise ValueError(
                f"vision_keywords_score must be in [0.0, 1.0], got {self.vision_keywords_score}"
            )

        if self.task_category not in VALID_TASK_CATEGORIES:
            raise ValueError(
                f"task_category must be one of {sorted(VALID_TASK_CATEGORIES)}, "
                f"got {self.task_category!r}"
            )


# ── RouteClassification ─────────────────────────────────────────────────

@dataclass
class RouteClassification:
    """Result of the routing classification step."""

    route: str
    confidence: float
    toolbox: list[str] = field(default_factory=lambda: ["all"])
    reasoning: str = ""

    def __post_init__(self) -> None:
        if self.route not in VALID_ROUTES:
            raise ValueError(
                f"route must be one of {sorted(VALID_ROUTES)}, got {self.route!r}"
            )

        # Clamp confidence to [0.0, 1.0]
        self.confidence = max(0.0, min(1.0, self.confidence))

        # Default toolbox if empty
        if not self.toolbox:
            self.toolbox = ["all"]


# ── RouterConfig ─────────────────────────────────────────────────────────

@dataclass
class RouterConfig:
    """Configuration thresholds for the routing pipeline."""

    swap_threshold: float = 0.7
    hitl_threshold: float = 0.6
    longctx_token_ratio: float = 0.80
    cloud_token_ratio: float = 0.80
    keyword_bypass_enabled: bool = True
    prefer_loaded_variant: bool = True

    def __post_init__(self) -> None:
        if not (0.0 < self.swap_threshold <= 1.0):
            raise ValueError(
                f"swap_threshold must be in (0.0, 1.0], got {self.swap_threshold}"
            )

        if not (0.0 < self.hitl_threshold <= 1.0):
            raise ValueError(
                f"hitl_threshold must be in (0.0, 1.0], got {self.hitl_threshold}"
            )

        if not (0.0 < self.longctx_token_ratio <= 1.0):
            raise ValueError(
                f"longctx_token_ratio must be in (0.0, 1.0], got {self.longctx_token_ratio}"
            )

        if not (0.0 < self.cloud_token_ratio <= 1.0):
            raise ValueError(
                f"cloud_token_ratio must be in (0.0, 1.0], got {self.cloud_token_ratio}"
            )
