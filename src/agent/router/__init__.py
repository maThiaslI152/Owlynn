"""
Multi-LLM Router package.

Public API: data models for feature extraction, classification, configuration,
and token budget estimation.
"""

from src.agent.router.models import (
    VALID_ROUTES,
    VALID_TASK_CATEGORIES,
    RouteClassification,
    RouterConfig,
    TaskFeatures,
)
from src.agent.router.feature_extractor import extract_features
from src.agent.router.classifier import RouteClassifier
from src.agent.router.selector import RouteSelector
from src.agent.router.budget import estimate_token_budget

__all__ = [
    "TaskFeatures",
    "RouteClassification",
    "RouterConfig",
    "RouteClassifier",
    "RouteSelector",
    "VALID_ROUTES",
    "VALID_TASK_CATEGORIES",
    "extract_features",
    "estimate_token_budget",
]
