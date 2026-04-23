"""
Property-based tests for auto-summarize protected message preservation.

# Feature: productivity-workspace-overhaul, Property 11: Auto-summarize preserves protected messages
# **Validates: Requirements 4.6**

Property 11 states:
    For any message list containing tool call results, user-provided facts,
    or pinned messages, the auto-summarize function should never remove or
    compress those messages — they must appear unchanged in the output
    message list.

We test that:
1. ToolMessages always survive summarization unchanged
2. Messages with pinned=True always survive unchanged
3. Messages with user_fact=True always survive unchanged
4. SystemMessages always survive unchanged
5. Any mix of protected message types all survive together
"""

import os
import sys
from unittest.mock import AsyncMock, patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest
from hypothesis import given, settings, assume, HealthCheck
from hypothesis import strategies as st
from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)

from src.agent.nodes.summarize import (
    _is_protected,
    _SUMMARIZE_THRESHOLD,
    auto_summarize_node,
)


# ── Strategies ───────────────────────────────────────────────────────────

# Non-empty text for message content
content_st = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N", "P", "Z")),
    min_size=1,
    max_size=100,
)

# Tool call IDs
tool_call_id_st = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N")),
    min_size=1,
    max_size=20,
).map(lambda s: f"tc_{s}")

# Protected message strategies
tool_message_st = st.builds(
    ToolMessage,
    content=content_st,
    tool_call_id=tool_call_id_st,
)

pinned_message_st = st.builds(
    lambda content: HumanMessage(content=content, additional_kwargs={"pinned": True}),
    content=content_st,
)

user_fact_message_st = st.builds(
    lambda content: HumanMessage(content=content, additional_kwargs={"user_fact": True}),
    content=content_st,
)

system_message_st = st.builds(SystemMessage, content=content_st)

# Any protected message
protected_message_st = st.one_of(
    tool_message_st,
    pinned_message_st,
    user_fact_message_st,
    system_message_st,
)

# At least 1 protected message, up to 5
protected_messages_st = st.lists(protected_message_st, min_size=1, max_size=5)

# Context window
context_window_st = st.integers(min_value=5000, max_value=200_000)

# Number of regular conversation turns (enough to have older messages)
num_turns_st = st.integers(min_value=12, max_value=20)


# ── Helpers ──────────────────────────────────────────────────────────────

def _make_turns(n: int) -> list[BaseMessage]:
    """Create n human/AI turn pairs (regular, non-protected messages)."""
    msgs: list[BaseMessage] = []
    for i in range(n):
        msgs.append(HumanMessage(content=f"User message {i}"))
        msgs.append(AIMessage(content=f"AI response {i}"))
    return msgs


def _build_message_list(
    num_turns: int,
    protected_msgs: list[BaseMessage],
) -> list[BaseMessage]:
    """Build a message list with protected messages inserted in the older section.

    Protected messages are placed early in the conversation (indices 2..2+len)
    so they fall in the 'older' portion that gets summarized.
    """
    regular = _make_turns(num_turns)
    # Insert protected messages after the first turn pair (index 2)
    for i, pmsg in enumerate(protected_msgs):
        regular.insert(2 + i, pmsg)
    return regular


# ═════════════════════════════════════════════════════════════════════════
# Property 11: Auto-summarize preserves protected messages
# ═════════════════════════════════════════════════════════════════════════

class TestProtectedMessagePreservation:
    """
    Property 11: For any message list containing tool call results,
    user-provided facts, or pinned messages, the auto-summarize function
    should never remove or compress those messages — they must appear
    unchanged in the output message list.

    **Validates: Requirements 4.6**
    """

    @given(
        num_turns=num_turns_st,
        protected_msgs=protected_messages_st,
        context_window=context_window_st,
    )
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    @pytest.mark.asyncio
    @patch("src.agent.nodes.summarize.get_small_llm")
    async def test_protected_messages_survive_summarization(
        self, mock_get_llm, num_turns, protected_msgs, context_window
    ):
        """
        For any set of protected messages (tool results, pinned, user facts,
        system messages) placed in the older portion of a conversation,
        after auto-summarize triggers, every protected message must appear
        in the output message list with identical content and type.
        """
        mock_llm = AsyncMock()
        mock_llm.ainvoke.return_value = AIMessage(
            content="- Summary point one\n- Summary point two"
        )
        mock_get_llm.return_value = mock_llm

        messages = _build_message_list(num_turns, protected_msgs)

        # Set active_tokens above threshold to trigger summarization
        active_tokens = int((_SUMMARIZE_THRESHOLD + 0.05) * context_window)

        state = {
            "messages": messages,
            "active_tokens": active_tokens,
            "context_window": context_window,
        }

        result = await auto_summarize_node(state)

        # If summarization triggered, verify all protected messages survived
        if result and "messages" in result:
            new_messages = result["messages"]
            for pmsg in protected_msgs:
                assert pmsg in new_messages, (
                    f"Protected message lost during summarization: "
                    f"type={type(pmsg).__name__}, content={pmsg.content!r}"
                )
                # Verify content is unchanged
                matched = [m for m in new_messages if m is pmsg]
                assert len(matched) == 1, (
                    f"Protected message should appear exactly once, "
                    f"found {len(matched)} for content={pmsg.content!r}"
                )
        else:
            # If no summarization happened (e.g., nothing old to summarize),
            # the original messages are untouched — protected messages are safe
            pass

    @given(
        num_turns=num_turns_st,
        protected_msgs=protected_messages_st,
        context_window=context_window_st,
    )
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    @pytest.mark.asyncio
    @patch("src.agent.nodes.summarize.get_small_llm")
    async def test_protected_message_content_unchanged(
        self, mock_get_llm, num_turns, protected_msgs, context_window
    ):
        """
        For any protected message that survives summarization, its content
        must be byte-for-byte identical to the original — no compression,
        truncation, or modification.
        """
        mock_llm = AsyncMock()
        mock_llm.ainvoke.return_value = AIMessage(
            content="- Summarized older conversation"
        )
        mock_get_llm.return_value = mock_llm

        messages = _build_message_list(num_turns, protected_msgs)

        # Record original content for comparison
        original_contents = [
            (type(m).__name__, m.content) for m in protected_msgs
        ]

        active_tokens = int((_SUMMARIZE_THRESHOLD + 0.05) * context_window)

        state = {
            "messages": messages,
            "active_tokens": active_tokens,
            "context_window": context_window,
        }

        result = await auto_summarize_node(state)

        if result and "messages" in result:
            new_messages = result["messages"]
            for pmsg, (orig_type, orig_content) in zip(
                protected_msgs, original_contents
            ):
                assert pmsg in new_messages, (
                    f"Protected {orig_type} message missing from output"
                )
                assert pmsg.content == orig_content, (
                    f"Protected message content was modified: "
                    f"expected {orig_content!r}, got {pmsg.content!r}"
                )

    @given(msg=protected_message_st)
    @settings(max_examples=100)
    def test_is_protected_identifies_all_protected_types(self, msg):
        """
        For any message generated from the protected message strategies,
        _is_protected must return True.
        """
        assert _is_protected(msg) is True, (
            f"_is_protected returned False for {type(msg).__name__} "
            f"with kwargs={getattr(msg, 'additional_kwargs', {})}"
        )
