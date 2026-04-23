"""
Property-based tests for auto-summarize trigger threshold.

# Feature: productivity-workspace-overhaul, Property 10: Auto-summarize trigger threshold
# **Validates: Requirements 4.1**

Property 10 states:
    For any conversation state, the auto-summarize process should trigger
    if and only if active_tokens > 0.85 * context_window.

We test the core threshold logic:
1. When active_tokens <= 0.85 * context_window, the node returns {} (no-op)
2. When active_tokens > 0.85 * context_window (with enough older messages),
   the node triggers summarization and returns a non-empty result
3. The exact boundary (active_tokens == 0.85 * context_window) is a no-op
"""

import os
import sys
from unittest.mock import AsyncMock, patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest
from hypothesis import given, settings, assume, HealthCheck
from hypothesis import strategies as st
from langchain_core.messages import AIMessage, HumanMessage

from src.agent.nodes.summarize import (
    _SUMMARIZE_THRESHOLD,
    auto_summarize_node,
)


# ── Strategies ───────────────────────────────────────────────────────────

# Context windows: realistic range from small (4K) to large (200K)
context_window_st = st.integers(min_value=1000, max_value=200_000)

# Fraction of context window for active tokens — below threshold
below_fraction_st = st.floats(
    min_value=0.0, max_value=_SUMMARIZE_THRESHOLD, allow_nan=False, allow_infinity=False
)

# Fraction of context window for active tokens — above threshold (strictly)
above_fraction_st = st.floats(
    min_value=_SUMMARIZE_THRESHOLD + 0.001,
    max_value=1.0,
    allow_nan=False,
    allow_infinity=False,
)


# ── Helpers ──────────────────────────────────────────────────────────────

def _make_turns(n: int) -> list:
    """Create n human/AI turn pairs."""
    msgs = []
    for i in range(n):
        msgs.append(HumanMessage(content=f"User message {i}"))
        msgs.append(AIMessage(content=f"AI response {i}"))
    return msgs


# We need enough turns so that older messages exist for summarization.
# _KEEP_RECENT_TURNS is 10, so 15 turns gives 5 older turns to summarize.
_ENOUGH_TURNS = 15


# ═════════════════════════════════════════════════════════════════════════
# Property 10: Auto-summarize trigger threshold
# ═════════════════════════════════════════════════════════════════════════

class TestAutoSummarizeTriggerThreshold:
    """
    Property 10: For any conversation state, the auto-summarize process
    should trigger if and only if active_tokens > 0.85 * context_window.

    **Validates: Requirements 4.1**
    """

    @given(
        context_window=context_window_st,
        fraction=below_fraction_st,
    )
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    @pytest.mark.asyncio
    async def test_no_trigger_when_below_threshold(self, context_window, fraction):
        """
        For any active_tokens <= 0.85 * context_window, the auto-summarize
        node should return an empty dict (no-op), regardless of message count.
        """
        active_tokens = int(fraction * context_window)
        # Ensure active_tokens is at or below threshold
        threshold = _SUMMARIZE_THRESHOLD * context_window
        assume(active_tokens <= threshold)

        state = {
            "messages": _make_turns(_ENOUGH_TURNS),
            "active_tokens": active_tokens,
            "context_window": context_window,
        }
        result = await auto_summarize_node(state)
        assert result == {}, (
            f"Expected no-op for active_tokens={active_tokens}, "
            f"threshold={threshold}, context_window={context_window}"
        )

    @given(
        context_window=context_window_st,
        fraction=above_fraction_st,
    )
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    @pytest.mark.asyncio
    @patch("src.agent.nodes.summarize.get_small_llm")
    async def test_triggers_when_above_threshold(
        self, mock_get_llm, context_window, fraction
    ):
        """
        For any active_tokens > 0.85 * context_window (with enough older
        messages), the auto-summarize node should trigger and return a
        non-empty result containing updated messages and summary data.
        """
        mock_llm = AsyncMock()
        mock_llm.ainvoke.return_value = AIMessage(
            content="- Summary point one\n- Summary point two"
        )
        mock_get_llm.return_value = mock_llm

        active_tokens = int(fraction * context_window)
        threshold = _SUMMARIZE_THRESHOLD * context_window
        assume(active_tokens > threshold)

        state = {
            "messages": _make_turns(_ENOUGH_TURNS),
            "active_tokens": active_tokens,
            "context_window": context_window,
        }
        result = await auto_summarize_node(state)

        assert result != {}, (
            f"Expected summarization for active_tokens={active_tokens}, "
            f"threshold={threshold}, context_window={context_window}"
        )
        assert "messages" in result, "Result should contain updated messages"
        assert "summary_takeaways" in result, "Result should contain takeaways"
        assert "context_summarized_event" in result, "Result should contain WS event"

    @given(context_window=context_window_st)
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    @pytest.mark.asyncio
    async def test_exact_boundary_does_not_trigger(self, context_window):
        """
        At exactly active_tokens == 0.85 * context_window, the node should
        NOT trigger (the condition is strictly greater-than, not >=).
        """
        active_tokens = int(_SUMMARIZE_THRESHOLD * context_window)

        state = {
            "messages": _make_turns(_ENOUGH_TURNS),
            "active_tokens": active_tokens,
            "context_window": context_window,
        }
        result = await auto_summarize_node(state)
        assert result == {}, (
            f"Expected no-op at exact boundary: active_tokens={active_tokens}, "
            f"threshold={_SUMMARIZE_THRESHOLD * context_window}, "
            f"context_window={context_window}"
        )
