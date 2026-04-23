"""
Route classifier for the Multi-LLM Router.

Uses the Small LLM to classify tasks into routing categories with a
confidence score. Falls back to safe defaults on any failure.
"""

from __future__ import annotations

import json
import logging
import re

from src.agent.router.models import RouteClassification, TaskFeatures, VALID_ROUTES

logger = logging.getLogger(__name__)

# Max characters of user input included in the classification prompt.
_MAX_INPUT_CHARS = 500

# ── Classification prompt ────────────────────────────────────────────────

_CLASSIFY_PROMPT = """\
You are a task router. Classify the user's request into a route.

Routes:
- simple: greetings, thanks, trivial questions
- complex-default: general coding, reasoning, multi-step tasks
- complex-vision: tasks involving images or visual content
- complex-longctx: long documents, large context tasks
- complex-cloud: frontier-quality reasoning, proofs, advanced math

Current model variant loaded: {current_variant}

Extracted features:
- has_images: {has_images}
- has_file_attachments: {has_file_attachments}
- estimated_input_tokens: {estimated_input_tokens}
- task_category: {task_category}
- document_keywords_score: {document_keywords_score:.2f}
- vision_keywords_score: {vision_keywords_score:.2f}
- has_tool_history: {has_tool_history}
- web_intent: {web_intent}
- frontier_quality_needed: {frontier_quality_needed}

User message (truncated): {user_input}

Reply with exactly one JSON object (no markdown, no extra text):
{{"route":"<route>","confidence":<0.0-1.0>,"toolbox":["<category>"],"reasoning":"<brief>"}}
"""


# ── Default classification (safe fallback) ───────────────────────────────

def _default_classification() -> RouteClassification:
    """Return safe default classification on any failure."""
    return RouteClassification(
        route="complex-default",
        confidence=0.5,
        toolbox=["all"],
        reasoning="fallback-default",
    )


# ── Parse helper (exposed for testability) ───────────────────────────────

def parse_classification(content: str) -> RouteClassification:
    """Parse a JSON string into a RouteClassification.

    Returns safe defaults if *content* is not valid JSON or is missing
    required fields.
    """
    try:
        match = re.search(r"\{.*\}", content, re.DOTALL)
        if not match:
            return _default_classification()

        parsed = json.loads(match.group(0))

        route = str(parsed.get("route", "complex-default")).lower().strip()
        if route not in VALID_ROUTES:
            route = "complex-default"

        confidence = float(parsed.get("confidence", 0.5))

        toolbox = parsed.get("toolbox", ["all"])
        if isinstance(toolbox, str):
            toolbox = [toolbox]
        if not toolbox:
            toolbox = ["all"]

        reasoning = str(parsed.get("reasoning", ""))

        return RouteClassification(
            route=route,
            confidence=confidence,
            toolbox=toolbox,
            reasoning=reasoning,
        )
    except Exception:
        return _default_classification()


# ── RouteClassifier ──────────────────────────────────────────────────────

class RouteClassifier:
    """Classifies user tasks using the Small LLM."""

    async def classify(
        self,
        user_text: str,
        features: TaskFeatures,
        current_variant: str | None,
        *,
        small_llm=None,
    ) -> RouteClassification:
        """Invoke Small LLM with a structured prompt and return a classification.

        On any LLM failure or parse error the method returns safe defaults
        (``route="complex-default"``, ``confidence=0.5``, ``toolbox=["all"]``).

        Parameters
        ----------
        small_llm:
            Optional pre-resolved Small LLM instance.  When ``None`` the
            classifier fetches one via ``get_small_llm()``.
        """
        try:
            if small_llm is None:
                from src.agent.llm import get_small_llm
                small_llm = await get_small_llm()

            prompt = _CLASSIFY_PROMPT.format(
                current_variant=current_variant or "none",
                has_images=features.has_images,
                has_file_attachments=features.has_file_attachments,
                estimated_input_tokens=features.estimated_input_tokens,
                task_category=features.task_category,
                document_keywords_score=features.document_keywords_score,
                vision_keywords_score=features.vision_keywords_score,
                has_tool_history=features.has_tool_history,
                web_intent=features.web_intent,
                frontier_quality_needed=features.frontier_quality_needed,
                user_input=json.dumps(user_text[:_MAX_INPUT_CHARS]),
            )

            router_llm = small_llm.bind(temperature=0.05, max_tokens=256)

            from langchain_core.messages import HumanMessage
            response = await router_llm.ainvoke([HumanMessage(content=prompt)])

            return parse_classification(response.content)
        except Exception as exc:
            logger.error("[classifier] Classification failed: %s", exc)
            return _default_classification()
