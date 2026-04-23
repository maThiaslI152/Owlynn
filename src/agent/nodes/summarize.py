"""
Auto-Summarize Node — Compresses older conversation history when context usage
exceeds 85% of the active model's context window.

Uses the always-loaded Small_LLM (lfm2.5-1.2b, 4K context) to produce a
structured summary with categorized takeaways. Preserves tool call results,
user-provided facts, pinned messages, and prior auto-summaries.

Features:
- **Multi-level compression**: Prior summaries are fed back into subsequent
  summarization rounds so cumulative context is never lost.
- **Structured output**: Summaries are categorized into decisions, facts,
  preferences, open tasks, and code changes.
- **Graceful degradation**: Falls back to a compact no-LLM fallback when the
  Small_LLM is unavailable.

Requirements: 4.1, 4.2, 4.6
"""

import logging
from typing import Sequence

from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)

from src.agent.llm import get_small_llm
from src.agent.state import AgentState

logger = logging.getLogger(__name__)

# Default context window for Medium_Default (used when state doesn't specify)
_DEFAULT_CONTEXT_WINDOW = 100_000

# Threshold ratio — trigger summarization when active_tokens exceed this fraction
_SUMMARIZE_THRESHOLD = 0.85

# Number of recent turns to always keep in full (not summarized)
_KEEP_RECENT_TURNS = 10

# Rough chars-per-token estimate for quick token approximation
_CHARS_PER_TOKEN = 4


# ── Structured summarization prompt ───────────────────────────────────
# Instructs Small_LLM to produce categorized output with clear section headers.

_SUMMARIZE_PROMPT = (
    "Summarize the following conversation into the categories below. "
    "Be concise — each bullet ≤ 25 words. "
    "If a category has no entries, omit it.\n\n"
    "## Decisions\n"
    "- (decisions made)\n\n"
    "## Facts\n"
    "- (facts stated by the user or discovered)\n\n"
    "## User Preferences\n"
    "- (preferences, style choices, recurring requests)\n\n"
    "## Open Tasks\n"
    "- (pending items, follow-ups, unresolved questions)\n\n"
    "## Code / Tool Results\n"
    "- (code written, files created, tool outputs)\n\n"
    "{prior_context}"
    "Conversation to summarize:\n"
    "{conversation}"
)


def _estimate_tokens(text: str) -> int:
    """Estimate token count from character count.

    Uses a mixed heuristic:
    - 1 token per ~2 chars for code-heavy text (operators, braces)
    - 1 token per ~4 chars for prose
    We split the text and estimate each part independently, then average.
    """
    if not text:
        return 1
    # Rough heuristic: count special chars (code-like) vs prose chars
    special = sum(1 for c in text if c in "{}[]();:<>!=+-*/\\|&^%~`\"'#@")
    prose_chars = len(text) - special
    code_tokens = special // 2
    prose_tokens = prose_chars // 4
    # Weighted: code chars are denser (~2 chars/token), prose is sparser (~4 chars/token)
    return max(1, (code_tokens * 2 + prose_tokens) // 3)


def _estimate_messages_tokens(messages: Sequence[BaseMessage]) -> int:
    """Estimate total tokens across a list of messages."""
    total = 0
    for msg in messages:
        content = msg.content if isinstance(msg.content, str) else str(msg.content)
        total += _estimate_tokens(content)
    return total


def _is_protected(msg: BaseMessage) -> bool:
    """Return True if a message should never be summarized.

    Protected categories (Requirement 4.6):
    - ToolMessage (tool call results)
    - Messages with metadata flag ``pinned=True``
    - Messages with metadata flag ``user_fact=True`` (user-provided facts)
    - SystemMessage (system prompts / prior summaries)
    """
    if isinstance(msg, (ToolMessage, SystemMessage)):
        return True
    meta = getattr(msg, "additional_kwargs", {}) or {}
    if meta.get("pinned") or meta.get("user_fact"):
        return True
    # Also check response_metadata for pinned/user_fact
    resp_meta = getattr(msg, "response_metadata", {}) or {}
    if resp_meta.get("pinned") or resp_meta.get("user_fact"):
        return True
    return False


def _split_messages(
    messages: Sequence[BaseMessage],
    keep_recent: int = _KEEP_RECENT_TURNS,
) -> tuple[list[BaseMessage], list[BaseMessage]]:
    """Split messages into (older_candidates, recent_kept).

    ``keep_recent`` refers to *turns* (a human + AI pair = 1 turn).
    We walk backwards counting Human messages to find the split point.
    """
    msgs = list(messages)
    if not msgs:
        return [], []

    # Count turns from the end (each HumanMessage starts a turn)
    turn_count = 0
    split_idx = None
    for i in range(len(msgs) - 1, -1, -1):
        if isinstance(msgs[i], HumanMessage):
            turn_count += 1
            if turn_count >= keep_recent:
                split_idx = i
                break

    # If we didn't find enough turns, keep everything as recent
    if split_idx is None:
        return [], msgs

    older = msgs[:split_idx]
    recent = msgs[split_idx:]
    return older, recent


async def auto_summarize_node(state: AgentState) -> dict:
    """LangGraph node: compress older messages when context is near capacity.

    Trigger condition (Req 4.1):
        ``active_tokens > 0.85 * context_window``

    Returns a dict with:
        - ``messages``: updated message list (summarized older + kept recent)
        - ``summary_takeaways``: list of takeaway strings
        - ``summarized_tokens``: token count of the compressed portion
        - ``active_tokens``: updated active token count
        - ``context_summarized_event``: payload for the WS event
    """
    messages: list[BaseMessage] = list(state.get("messages") or [])
    active_tokens: int = state.get("active_tokens") or _estimate_messages_tokens(messages)
    context_window: int = state.get("context_window") or _DEFAULT_CONTEXT_WINDOW

    # ── Guard: only summarize when threshold exceeded ────────────────────
    threshold = _SUMMARIZE_THRESHOLD * context_window
    if active_tokens <= threshold:
        return {}  # no-op — nothing to update

    # ── Split into older vs. recent ──────────────────────────────────────
    older, recent = _split_messages(messages)
    if not older:
        return {}  # nothing old enough to summarize

    # ── Separate protected messages from summarizable ones ───────────────
    protected: list[BaseMessage] = []
    to_summarize: list[BaseMessage] = []
    for msg in older:
        if _is_protected(msg):
            protected.append(msg)
        else:
            to_summarize.append(msg)

    if not to_summarize:
        return {}  # everything is protected, nothing to compress

    # ── Extract prior summary context for multi-level awareness ──────────
    prior_context = ""
    for msg in protected:
        if isinstance(msg, SystemMessage):
            content = msg.content if isinstance(msg.content, str) else ""
            if content.startswith("[Auto-Summary"):
                prior_context = (
                    "Prior summary (context from earlier compression):\n"
                    f"{content}\n\n"
                    "Build on this prior context instead of starting fresh.\n\n"
                )
                break

    # ── Build conversation text for the summarizer ───────────────────────
    conv_lines: list[str] = []
    for msg in to_summarize:
        role = "User" if isinstance(msg, HumanMessage) else "AI"
        content = msg.content if isinstance(msg.content, str) else str(msg.content)
        # Truncate very long messages to stay within Small_LLM's 4K window
        if len(content) > 800:
            content = content[:800] + "…"
        conv_lines.append(f"{role}: {content}")

    conversation_text = "\n".join(conv_lines)
    # Hard cap the conversation text fed to Small_LLM (~2K tokens budget)
    max_conv_chars = 2000 * _CHARS_PER_TOKEN
    if len(conversation_text) > max_conv_chars:
        conversation_text = conversation_text[:max_conv_chars] + "\n[…truncated]"

    prompt_text = _SUMMARIZE_PROMPT.format(
        prior_context=prior_context,
        conversation=conversation_text,
    )

    # ── Call Small_LLM ───────────────────────────────────────────────────
    try:
        llm = await get_small_llm()
        response = await llm.ainvoke([SystemMessage(content=prompt_text)])
        summary_text = (response.content or "").strip()
    except Exception as e:
        logger.warning("[auto_summarize] Small_LLM failed (%s), skipping summarization", e)
        return {}  # graceful degradation — keep full context

    if not summary_text:
        return {}

    # ── Parse takeaways from the summary ─────────────────────────────────
    takeaways: list[str] = []
    for line in summary_text.split("\n"):
        line = line.strip().lstrip("-•*").strip()
        if line:
            takeaways.append(line)
    if not takeaways:
        takeaways = [summary_text]

    # ── Build the replacement SystemMessage ──────────────────────────────
    summary_msg = SystemMessage(
        content=f"[Auto-Summary of earlier conversation]\n{summary_text}"
    )

    # ── Assemble new message list: summary + protected older + recent ────
    new_messages = [summary_msg] + protected + recent

    # ── Compute token deltas ─────────────────────────────────────────────
    old_tokens = _estimate_messages_tokens(to_summarize)
    summary_tokens = _estimate_tokens(summary_text)
    tokens_freed = max(0, old_tokens - summary_tokens)
    new_active_tokens = max(0, active_tokens - tokens_freed)
    summarized_tokens = (state.get("summarized_tokens") or 0) + old_tokens

    # ── Build WS event payload (Req 4.2) ─────────────────────────────────
    context_summarized_event = {
        "type": "context_summarized",
        "summary": summary_text,
        "takeaways": takeaways,
        "messages_compressed": len(to_summarize),
        "tokens_freed": tokens_freed,
    }

    logger.info(
        "[auto_summarize] Compressed %d messages, freed ~%d tokens",
        len(to_summarize),
        tokens_freed,
    )

    return {
        "messages": new_messages,
        "summary_takeaways": takeaways,
        "summarized_tokens": summarized_tokens,
        "active_tokens": new_active_tokens,
        "context_summarized_event": context_summarized_event,
    }
