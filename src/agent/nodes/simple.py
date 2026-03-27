"""
Simple Node — Fast answers via the small LLM (LFM2.5-1.2B or similar).

Handles greetings, small talk, and direct knowledge questions.
No tools, no memory injection (keeps the prompt short for small models).
Falls back to the large model if the small one fails.
"""

import logging
import re

from langchain_core.messages import AIMessage, SystemMessage
from src.agent.llm import get_small_llm
from src.agent.response_styles import style_instruction_for_prompt
from src.agent.lm_studio_compat import with_system_for_local_server
from src.agent.state import AgentState

logger = logging.getLogger(__name__)

SIMPLE_PROMPT = (
    "You are Owlynn, a helpful assistant. "
    "Give short, direct answers (1-3 sentences). "
    "No reasoning steps, no preamble, no meta commentary."
    "{style_hint}"
)


def _clean_response(text: str) -> str:
    """Strip thinking tokens and reasoning artifacts from small model output."""
    if not text:
        return ""
    # Remove <think>...</think> blocks
    out = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
    # Remove numbered reasoning steps (e.g. "1. **Analyze**...")
    lines = out.split("\n")
    kept: list[str] = []
    skip = False
    for line in lines:
        s = line.strip()
        if re.match(r"^\d+\.\s+\*\*", s) or s.startswith("Thinking Process:"):
            skip = True
            continue
        if skip and not s:
            continue
        if s and not s.startswith("*   "):
            skip = False
            kept.append(line)
    result = "\n".join(kept).strip()
    if not result:
        # Fallback: extract quoted strings from reasoning
        quotes = re.findall(r'"([^"]{5,})"', out)
        result = quotes[-1] if quotes else out
    return result or text


async def simple_node(state: AgentState) -> AgentState:
    """Fast-path node: short answers without tools."""
    style_hint = style_instruction_for_prompt(state.get("response_style"))
    system = SystemMessage(content=SIMPLE_PROMPT.format(style_hint=style_hint))
    messages = list(state.get("messages") or [])
    prompt = with_system_for_local_server(system, messages)

    # Try small model, fall back to large on failure
    try:
        llm = await get_small_llm()
        response = await llm.bind(temperature=0.4, max_tokens=512).ainvoke(prompt)
        content = _clean_response(response.content or "")
        model = "small"
    except Exception as e:
        logger.warning("[simple] Small model failed (%s), falling back to large", e)
        from src.agent.llm import get_large_llm
        llm = await get_large_llm()
        response = await llm.bind(temperature=0.4, max_tokens=512).ainvoke(prompt)
        content = _clean_response(response.content or "")
        model = "large"

    return {"messages": [AIMessage(content=content)], "model_used": model}
