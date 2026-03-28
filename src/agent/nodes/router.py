"""
Router Node — 5-way routing with toolbox selection and HITL clarification.
--------------------------------------------------------------------------
Uses the Small LLM to classify: simple vs complex, then selects the
appropriate M-tier variant or cloud escalation for complex tasks.
Also selects toolbox categories for dynamic tool loading.
"""

from langchain_core.messages import HumanMessage
from langgraph.types import interrupt

from src.agent.state import AgentState
from src.agent.llm import get_small_llm, LLMPool
from src.config.settings import MEDIUM_DEFAULT_CONTEXT, MEDIUM_LONGCTX_CONTEXT, CLOUD_CONTEXT
from src.memory.user_profile import get_profile

import json
import re
import logging

logger = logging.getLogger(__name__)


# ── Context window constants per model tier ──────────────────────────────
_MEDIUM_DEFAULT_CONTEXT = MEDIUM_DEFAULT_CONTEXT   # 100000
_MEDIUM_LONGCTX_CONTEXT = MEDIUM_LONGCTX_CONTEXT   # 131072
_CLOUD_CONTEXT = CLOUD_CONTEXT                     # 131072
_SMALL_MODEL_CONTEXT = 4096

# Tier definitions: (max_input_chars, token_budget)
_BUDGET_TIERS = [
    # Greetings / tiny questions
    (40,   256),
    # Short questions ("what is X?", "how do I Y?")
    (150,  512),
    # Medium questions, single-topic explanations
    (400,  1536),
    # Longer prompts, multi-part questions
    (800,  3072),
    # Complex / code-heavy / multi-step requests
    (1600, 4096),
]

# Keywords that signal the user wants a long/detailed answer
_LONG_ANSWER_HINTS = {
    "explain", "write", "create", "implement", "build", "generate",
    "refactor", "analyze", "compare", "review", "summarize", "translate",
    "step by step", "in detail", "full code", "complete",
}

# Keywords that signal a short answer is fine
_SHORT_ANSWER_HINTS = {
    "yes or no", "true or false", "which one", "what is",
    "how much", "how many", "when", "where",
}


def estimate_token_budget(user_text: str, route: str) -> int:
    """
    Estimate a reasonable max_tokens budget for the response.

    Uses per-tier context windows:
    - simple → _SMALL_MODEL_CONTEXT (4096) with 1500 reserve
    - complex-cloud → _CLOUD_CONTEXT (131072) with 8000 reserve, budget_max 16384
    - complex-longctx → _MEDIUM_LONGCTX_CONTEXT (131072) with 4000 reserve, budget_max 8192
    - complex-default, complex-vision → _MEDIUM_DEFAULT_CONTEXT (100000) with 4000 reserve, budget_max 8192
    """
    if route == "simple":
        budget = 256
        if len(user_text) > 100:
            budget = 512
        return min(budget, _SMALL_MODEL_CONTEXT - 1500)

    # Determine context window and reserves based on route
    if route == "complex-cloud":
        context = _CLOUD_CONTEXT
        input_reserve = 8000
        budget_max = 16384
    elif route == "complex-longctx":
        context = _MEDIUM_LONGCTX_CONTEXT
        input_reserve = 4000
        budget_max = 8192
    else:  # complex-default, complex-vision
        context = _MEDIUM_DEFAULT_CONTEXT
        input_reserve = 4000
        budget_max = 8192

    text_len = len(user_text)
    text_lower = user_text.lower()

    # Start with tier-based estimate from input length
    budget = budget_max
    for max_chars, tier_budget in _BUDGET_TIERS:
        if text_len <= max_chars:
            budget = min(tier_budget, budget_max)
            break

    # Boost if the user is asking for something that needs a long answer
    if any(hint in text_lower for hint in _LONG_ANSWER_HINTS):
        budget = max(budget, 3072)

    # Cap if the user is asking a short-answer question
    if any(hint in text_lower for hint in _SHORT_ANSWER_HINTS):
        budget = min(budget, 1536)

    # Longer input text eats into the context window — reduce output budget
    # Rough heuristic: ~4 chars per token for English
    estimated_input_tokens = input_reserve + (text_len // 4)
    available = context - estimated_input_tokens
    budget = min(budget, max(available, 512))  # Never go below 512 for complex

    return budget


# ── Router prompt with toolbox classification ────────────────────────────
ROUTER_PROMPT = """Classify in one shot. No reasoning, no preamble, no markdown.

simple = greetings/thanks/small talk OR a direct question answerable without tools or heavy reasoning.
complex = code/math/writing, multi-step work, OR needs live web/news/weather/prices.

Toolbox categories (pick one or more, or "all" if unsure):
- web_search: web lookup, live data, current information, news, weather, prices
- file_ops: read/write/edit/list/delete workspace files
- data_viz: create documents/spreadsheets/presentations/PDFs, run code, data analysis, charts
- productivity: task management, todos, skills, workflow templates
- memory: recall past conversations, user preferences, stored facts
- all: when unsure or multiple categories needed

Reply with exactly one JSON object (nothing else):
{{"routing":"simple"|"complex","confidence":0.0-1.0,"toolbox":"toolbox_name"|["name1","name2"]}}

Message: {user_input}

JSON:"""


def _last_user_text(state: AgentState) -> str:
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


def parse_routing(content: str) -> tuple[str, float, list[str]]:
    """Extract routing decision, confidence, and toolbox from LLM response."""
    try:
        match = re.search(r'\{.*\}', content, re.DOTALL)
        if match:
            parsed = json.loads(match.group(0))
            decision = parsed.get("routing", "complex").lower().strip()
            if decision not in ("simple", "complex"):
                decision = "complex"
            confidence = float(parsed.get("confidence", 0.5))
            toolbox = parsed.get("toolbox", "all")
            if isinstance(toolbox, str):
                toolbox = [toolbox]
            return decision, confidence, toolbox
    except Exception:
        pass
    return "complex", 0.5, ["all"]


# ── Image / frontier detection helpers ───────────────────────────────────

def _has_image_content(state: AgentState) -> bool:
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


_FRONTIER_HINTS = {
    "prove", "theorem", "formal proof", "mathematical proof",
    "symbolic", "calculus", "differential equation",
    "optimize algorithm", "complexity proof",
    "best possible", "highest quality", "frontier",
}


def _needs_frontier_quality(text: str) -> bool:
    """Check if the task needs frontier-class model quality."""
    lower = text.lower()
    return any(hint in lower for hint in _FRONTIER_HINTS)


# When web search is enabled, these usually need the large model + tools.
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


def _resolve_complex_route(
    user_text: str,
    state: AgentState,
    toolbox: list[str],
) -> tuple[str, list[str]]:
    """
    Stage 2: given a complex classification, pick the specific route.

    Returns (route, toolbox) — toolbox may be adjusted.
    """
    # 1. Image attachments → complex-vision
    if _has_image_content(state):
        return "complex-vision", toolbox

    # 2. Estimate input tokens (rough: ~4 chars per token)
    text_len = len(user_text)
    estimated_input = 4000 + (text_len // 4)  # input_reserve + message tokens

    # 3. Exceeds Medium_LongCtx → cloud
    if estimated_input > _MEDIUM_LONGCTX_CONTEXT * 0.80:
        return "complex-cloud", toolbox

    # 4. Exceeds 80% of Medium_Default → longctx
    if estimated_input > _MEDIUM_DEFAULT_CONTEXT * 0.80:
        return "complex-longctx", toolbox

    # 5. Frontier-quality indicators → cloud
    if _needs_frontier_quality(user_text):
        return "complex-cloud", toolbox

    # 6. Default
    return "complex-default", toolbox


def _check_cloud_available() -> bool:
    """Check if cloud escalation is possible (API key + enabled)."""
    profile = get_profile()
    if not profile.get("cloud_escalation_enabled", True):
        return False
    # Check API key via LLMPool's resolution logic
    api_key = LLMPool._resolve_deepseek_api_key()
    return bool(api_key)


async def router_node(state: AgentState) -> AgentState:
    """Route to simple or complex path with 5-way variant selection and toolbox."""
    messages = state.get("messages", [])
    if not messages:
        return {"route": "complex-default", "selected_toolboxes": ["all"],
                "router_clarification_used": False}

    user_text = _last_user_text(state)
    user_lower = user_text.lower()

    # If the conversation already used tools or the large model, stay on complex.
    if len(messages) > 2:
        has_tool_history = any(
            getattr(m, "type", None) == "tool" or hasattr(m, "tool_calls") and m.tool_calls
            for m in messages[:-1]
        )
        if has_tool_history:
            logger.info("[router] Complex path — conversation has tool history")
            route, toolbox = _resolve_complex_route(user_text, state, ["all"])
            return {"route": route, "token_budget": estimate_token_budget(user_text, route),
                    "selected_toolboxes": toolbox, "router_clarification_used": False}

    web_on = state.get("web_search_enabled")
    if web_on is None:
        web_on = True

    if web_on and any(h in user_lower for h in _WEBISH_HINTS):
        logger.info("[router] Complex path — web/live-data intent (web_search enabled)")
        route, toolbox = _resolve_complex_route(user_text, state, ["web_search"])
        return {"route": route, "token_budget": estimate_token_budget(user_text, route),
                "selected_toolboxes": toolbox, "router_clarification_used": False}

    # Attachments saved to workspace need the large model + tools.
    if (
        "[file:" in user_lower
        or "uploaded to workspace" in user_lower
        or "workspace file" in user_lower
    ):
        logger.info("[router] Complex path — workspace / attachment context")
        route, toolbox = _resolve_complex_route(user_text, state, ["file_ops"])
        return {"route": route, "token_budget": estimate_token_budget(user_text, route),
                "selected_toolboxes": toolbox, "router_clarification_used": False}

    # Quick keyword check to bypass LLM for obvious simple cases.
    simple_keywords = [
        "hello", "hi", "hey", "thanks", "thank you",
        "bye", "goodbye", "what time", "what date",
    ]
    for kw in simple_keywords:
        if kw in user_lower:
            logger.info("[router] Simple path - keyword match")
            return {"route": "simple", "token_budget": estimate_token_budget(user_text, "simple"),
                    "selected_toolboxes": ["all"], "router_clarification_used": False}

    # ── Stage 1: Ask Small LLM for simple/complex + toolbox ──────────────
    small_llm = await get_small_llm()
    decision = "complex"
    confidence = 0.5
    toolbox = ["all"]

    try:
        router_llm = small_llm.bind(temperature=0.05, max_tokens=128)
        response = await router_llm.ainvoke(
            [HumanMessage(
                content=ROUTER_PROMPT.format(user_input=json.dumps(user_text[:500]))
            )]
        )
        decision, confidence, toolbox = parse_routing(response.content)
    except Exception as e:
        logger.error(f"[router] Error during routing: {e}")
        decision, confidence, toolbox = "complex", 0.5, ["all"]

    # ── HITL clarification when confidence is low ────────────────────────
    profile = get_profile()
    router_hitl_enabled = profile.get("router_hitl_enabled", True)
    threshold = float(profile.get("router_clarification_threshold", 0.6))

    router_clarification_used = False
    if confidence < threshold and router_hitl_enabled:
        try:
            clarification = interrupt({
                "type": "ask_user",
                "question": "I'm not sure how to handle this. What would you prefer?",
                "choices": [
                    {"label": "Search the web", "route": "complex-default", "toolbox": ["web_search"]},
                    {"label": "Work with local files", "route": "complex-default", "toolbox": ["file_ops"]},
                    {"label": "Create documents/visualizations", "route": "complex-default", "toolbox": ["data_viz"]},
                    {"label": "Use cloud model for higher quality", "route": "complex-cloud", "toolbox": ["all"]},
                    {"label": "Just answer directly", "route": "complex-default", "toolbox": ["all"]},
                ],
            })
            router_clarification_used = True
            # Use clarification response to finalize routing
            if isinstance(clarification, dict):
                decision = "complex"
                toolbox = clarification.get("toolbox", ["all"])
                route_override = clarification.get("route", "complex-default")
                logger.info(f"[router] HITL clarification → route={route_override}, toolbox={toolbox}")
                budget = estimate_token_budget(user_text, route_override)
                # Check cloud availability for cloud route
                if route_override == "complex-cloud" and not _check_cloud_available():
                    route_override = "complex-default"
                    logger.warning("[router] Cloud unavailable, falling back to complex-default")
                return {"route": route_override, "token_budget": budget,
                        "selected_toolboxes": toolbox,
                        "router_clarification_used": True}
        except Exception as e:
            logger.warning(f"[router] HITL interrupt failed: {e}")

    # ── Finalize route ───────────────────────────────────────────────────
    if decision == "simple":
        logger.info(f"[router] → simple (confidence={confidence:.2f})")
        return {"route": "simple", "token_budget": estimate_token_budget(user_text, "simple"),
                "selected_toolboxes": toolbox, "router_clarification_used": router_clarification_used}

    # Stage 2: complex variant selection
    route, toolbox = _resolve_complex_route(user_text, state, toolbox)

    # If cloud route but cloud unavailable, downgrade
    if route == "complex-cloud" and not _check_cloud_available():
        # Check if longctx fits
        estimated_input = 4000 + (len(user_text) // 4)
        if estimated_input > _MEDIUM_DEFAULT_CONTEXT * 0.80:
            route = "complex-longctx"
        else:
            route = "complex-default"
        logger.warning(f"[router] Cloud unavailable, downgraded to {route}")

    logger.info(f"[router] → {route} (confidence={confidence:.2f}, toolbox={toolbox})")
    return {"route": route, "token_budget": estimate_token_budget(user_text, route),
            "selected_toolboxes": toolbox, "router_clarification_used": router_clarification_used}


# ── Chat title generation (unchanged) ───────────────────────────────────

CHAT_TITLE_PROMPT = """You are a helpful assistant that proposes a short chat title.

Rules:
- Output ONLY valid JSON (no markdown, no extra keys).
- Title must be concise and human-friendly.
- Prefer the main intent/topic from the user's message.

JSON format:
{{"title":"..."}}

User message: {user_input}
Attached file names: {file_names}
"""


def _parse_title_json(content: str) -> str:
    """
    Best-effort extraction of `{"title":"..."}` from model output.
    Returns empty string if parsing fails.
    """
    try:
        match = re.search(r"\{.*\}", content, re.DOTALL)
        if not match:
            return ""
        parsed = json.loads(match.group(0))
        title = str(parsed.get("title", "")).strip()
        return title
    except Exception:
        return ""


async def generate_chat_title_router_llm(
    user_text: str,
    file_names: list[str] | None = None,
) -> str:
    """
    Generate a chat title using the router's small LLM.

    This is intentionally lightweight: we only ask for a single JSON title object.
    """
    user_text = str(user_text or "").strip()
    if not user_text:
        return ""

    file_names = file_names or []
    joined_files = ", ".join([str(n).strip() for n in file_names if n])
    joined_files = joined_files[:400]  # avoid massive prompts

    small_llm = await get_small_llm()

    router_llm = small_llm.bind(temperature=0.2, max_tokens=64)
    response = await router_llm.ainvoke(
        [HumanMessage(content=CHAT_TITLE_PROMPT.format(user_input=user_text[:1000], file_names=joined_files))]
    )

    title = _parse_title_json(getattr(response, "content", "") or "")
    # Normalize / truncate to keep UI clean (frontend also truncates as fallback).
    title = re.sub(r"\s+", " ", title).strip()
    if not title:
        return ""
    return title[:60]
