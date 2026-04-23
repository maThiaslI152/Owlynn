"""Unit tests for the auto-summarize node (src/agent/nodes/summarize.py).

Tests cover:
- Threshold gating (Req 4.1)
- Protected message preservation (Req 4.6)
- Message splitting logic
- Summary output structure (Req 4.2)
"""

import sys
from unittest.mock import AsyncMock, MagicMock, patch

# Stub mem0 before any project imports
sys.modules["mem0"] = MagicMock()

import pytest
from langchain_core.messages import (
    AIMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)

from src.agent.nodes.summarize import (
    _estimate_tokens,
    _estimate_messages_tokens,
    _is_protected,
    _split_messages,
    _SUMMARIZE_THRESHOLD,
    auto_summarize_node,
)


# ── Helper to build a conversation with N turns ──────────────────────────

def _make_turns(n: int) -> list:
    """Create n human/AI turn pairs."""
    msgs = []
    for i in range(n):
        msgs.append(HumanMessage(content=f"User message {i}"))
        msgs.append(AIMessage(content=f"AI response {i}"))
    return msgs


# ── _estimate_tokens ─────────────────────────────────────────────────────

class TestEstimateTokens:
    def test_empty_string(self):
        assert _estimate_tokens("") == 1  # min 1

    def test_short_string(self):
        assert _estimate_tokens("hello") == 1

    def test_longer_string(self):
        text = "a" * 100
        # 100 prose chars -> 100//4=25, 0 code chars -> 0//2=0, weighted (0*2+25)//3 = 8
        assert _estimate_tokens(text) == 8


# ── _is_protected ────────────────────────────────────────────────────────

class TestIsProtected:
    def test_tool_message_is_protected(self):
        msg = ToolMessage(content="result", tool_call_id="tc1")
        assert _is_protected(msg) is True

    def test_system_message_is_protected(self):
        msg = SystemMessage(content="system prompt")
        assert _is_protected(msg) is True

    def test_human_message_not_protected(self):
        msg = HumanMessage(content="hello")
        assert _is_protected(msg) is False

    def test_ai_message_not_protected(self):
        msg = AIMessage(content="hi there")
        assert _is_protected(msg) is False

    def test_pinned_message_is_protected(self):
        msg = HumanMessage(content="important", additional_kwargs={"pinned": True})
        assert _is_protected(msg) is True

    def test_user_fact_message_is_protected(self):
        msg = HumanMessage(content="my name is X", additional_kwargs={"user_fact": True})
        assert _is_protected(msg) is True


# ── _split_messages ──────────────────────────────────────────────────────

class TestSplitMessages:
    def test_empty_messages(self):
        older, recent = _split_messages([])
        assert older == []
        assert recent == []

    def test_fewer_than_keep_recent(self):
        msgs = _make_turns(5)  # 5 turns < 10 keep_recent
        older, recent = _split_messages(msgs, keep_recent=10)
        assert older == []
        assert recent == msgs

    def test_exact_keep_recent(self):
        msgs = _make_turns(10)
        older, recent = _split_messages(msgs, keep_recent=10)
        assert older == []
        assert recent == msgs

    def test_more_than_keep_recent(self):
        msgs = _make_turns(15)  # 15 turns, keep 10
        older, recent = _split_messages(msgs, keep_recent=10)
        assert len(older) > 0
        assert len(recent) > 0
        # Recent should contain at least 10 turns worth of HumanMessages
        recent_human = [m for m in recent if isinstance(m, HumanMessage)]
        assert len(recent_human) >= 10

    def test_split_preserves_all_messages(self):
        msgs = _make_turns(20)
        older, recent = _split_messages(msgs, keep_recent=10)
        assert older + recent == msgs


# ── auto_summarize_node ──────────────────────────────────────────────────

class TestAutoSummarizeNode:
    @pytest.mark.asyncio
    async def test_no_op_below_threshold(self):
        """Should return empty dict when tokens are below 85% threshold."""
        state = {
            "messages": _make_turns(5),
            "active_tokens": 1000,
            "context_window": 100_000,
        }
        result = await auto_summarize_node(state)
        assert result == {}

    @pytest.mark.asyncio
    async def test_no_op_when_nothing_old(self):
        """Should return empty dict when all messages are recent."""
        state = {
            "messages": _make_turns(5),
            "active_tokens": 90_000,  # above threshold
            "context_window": 100_000,
        }
        result = await auto_summarize_node(state)
        assert result == {}  # only 5 turns, all kept as recent

    @pytest.mark.asyncio
    @patch("src.agent.nodes.summarize.get_small_llm")
    async def test_summarizes_when_above_threshold(self, mock_get_llm):
        """Should summarize older messages when above 85% threshold."""
        mock_llm = AsyncMock()
        mock_llm.ainvoke.return_value = AIMessage(
            content="- User discussed project setup\n- AI helped with config"
        )
        mock_get_llm.return_value = mock_llm

        state = {
            "messages": _make_turns(15),
            "active_tokens": 90_000,
            "context_window": 100_000,
        }
        result = await auto_summarize_node(state)

        assert "messages" in result
        assert "summary_takeaways" in result
        assert "context_summarized_event" in result
        assert len(result["summary_takeaways"]) == 2
        event = result["context_summarized_event"]
        assert event["type"] == "context_summarized"
        assert "takeaways" in event
        assert event["messages_compressed"] > 0

    @pytest.mark.asyncio
    @patch("src.agent.nodes.summarize.get_small_llm")
    async def test_preserves_protected_messages(self, mock_get_llm):
        """Protected messages (tool results, pinned, system) must survive."""
        mock_llm = AsyncMock()
        mock_llm.ainvoke.return_value = AIMessage(content="- Summary point")
        mock_get_llm.return_value = mock_llm

        # Build messages with protected ones in the older section
        msgs = _make_turns(15)
        # Insert a ToolMessage and a pinned message early in the conversation
        tool_msg = ToolMessage(content="tool result", tool_call_id="tc1")
        pinned_msg = HumanMessage(content="pinned fact", additional_kwargs={"pinned": True})
        msgs.insert(2, tool_msg)
        msgs.insert(3, pinned_msg)

        state = {
            "messages": msgs,
            "active_tokens": 90_000,
            "context_window": 100_000,
        }
        result = await auto_summarize_node(state)

        assert "messages" in result
        new_msgs = result["messages"]
        # Protected messages should still be present
        assert tool_msg in new_msgs
        assert pinned_msg in new_msgs

    @pytest.mark.asyncio
    @patch("src.agent.nodes.summarize.get_small_llm")
    async def test_graceful_on_llm_failure(self, mock_get_llm):
        """Should return empty dict if Small_LLM fails."""
        mock_get_llm.side_effect = Exception("LLM unavailable")

        state = {
            "messages": _make_turns(15),
            "active_tokens": 90_000,
            "context_window": 100_000,
        }
        result = await auto_summarize_node(state)
        assert result == {}

    @pytest.mark.asyncio
    async def test_threshold_boundary_exact(self):
        """At exactly 85% threshold, should NOT trigger (uses > not >=)."""
        state = {
            "messages": _make_turns(15),
            "active_tokens": 85_000,  # exactly 0.85 * 100_000
            "context_window": 100_000,
        }
        result = await auto_summarize_node(state)
        assert result == {}
