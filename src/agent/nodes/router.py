"""
Router Node - Optimized for M4
-------------------------------
Uses the Small LLM to quickly decide: simple response or complex reasoning.
Simplified from 4 routes to 2 for M4 efficiency.
"""

from langchain_core.messages import HumanMessage
from src.agent.state import AgentState
from src.agent.llm import get_small_llm
import json
import re
import logging

logger = logging.getLogger(__name__)

# Router: minimal tokens; reasoning-style small models get a hard "no deliberation" instruction.
ROUTER_PROMPT = """Classify in one shot. No reasoning, no preamble, no markdown.

simple = greetings/thanks/small talk OR a direct question answerable without tools or heavy reasoning.
complex = code/math/writing, multi-step work, OR needs live web/news/weather/prices.

Reply with exactly one JSON object (nothing else):
{{"routing":"simple"|"complex","confidence":0.0-1.0}}

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


def parse_routing(content: str) -> str:
    """Extract routing decision from LLM response."""
    try:
        match = re.search(r'\{.*\}', content, re.DOTALL)
        if match:
            parsed = json.loads(match.group(0))
            decision = parsed.get("routing", "complex").lower().strip()
            if decision in ["simple", "complex"]:
                return decision
    except Exception:
        pass
    return "complex"  # Safe default (use large model if unsure)


# When web search is enabled, these usually need the large model + tools (not the small fast path).
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
    "price",  # e.g. product pricing (avoid matching very short words — "price" is 5 chars)
    "today's ",
    "right now",
    "live score",
)


async def router_node(state: AgentState) -> AgentState:
    """Route to simple or complex path based on quick analysis."""
    messages = state.get("messages", [])
    if not messages:
        return {"route": "complex"}

    user_text = _last_user_text(state)
    user_lower = user_text.lower()

    web_on = state.get("web_search_enabled")
    if web_on is None:
        web_on = True

    if web_on and any(h in user_lower for h in _WEBISH_HINTS):
        logger.info("[router] Complex path — web/live-data intent (web_search enabled)")
        return {"route": "complex"}

    # Attachments saved to workspace need the large model + tools (read_workspace_file, etc.).
    if (
        "[file:" in user_lower
        or "uploaded to workspace" in user_lower
        or "workspace file" in user_lower
    ):
        logger.info("[router] Complex path — workspace / attachment context")
        return {"route": "complex"}

    # Quick keyword check to bypass LLM for obvious cases (saves ~1s).
    # NOTE: Do NOT include "weather" here — that must use complex + web_search when enabled.
    simple_keywords = [
        "hello",
        "hi",
        "hey",
        "thanks",
        "thank you",
        "bye",
        "goodbye",
        "what time",
        "what date",
    ]
    for kw in simple_keywords:
        if kw in user_lower:
            logger.info("[router] Simple path - keyword match")
            return {"route": "simple"}

    # Get small LLM (pooled instance - no reinit overhead)
    small_llm = await get_small_llm()

    try:
        # LM Studio Qwen templates expect a **user** message; system-only breaks Jinja.
        router_llm = small_llm.bind(temperature=0.05, max_tokens=96)
        response = await router_llm.ainvoke(
            [
                HumanMessage(
                    content=ROUTER_PROMPT.format(user_input=json.dumps(user_text[:500]))
                ),
            ]
        )
        decision = parse_routing(response.content)
    except Exception as e:
        logger.error(f"[router] Error during routing: {e}")
        decision = "complex"  # Safe fallback

    logger.info(f"[router] → {decision}")
    return {"route": decision}


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
