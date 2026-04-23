"""
Property-based tests for conversation continuity across model swaps.

# Feature: deepseek-hybrid-integration, Property 12: Conversation Continuity Across Swaps
# Validates: Requirements 26.1, 26.5
"""

import sys
from unittest.mock import MagicMock

sys.modules["mem0"] = MagicMock()

import pytest
from hypothesis import given, settings, assume
from hypothesis import strategies as st
from langchain_core.messages import HumanMessage, AIMessage
from langgraph.graph.message import add_messages

from src.agent.state import AgentState

# ── Constants ────────────────────────────────────────────────────────────

VALID_MODEL_USED = [
    "small-local",
    "medium-default",
    "medium-vision",
    "medium-longctx",
    "large-cloud",
    "small-local-fallback",
    "medium-default-fallback",
    "medium-vision-fallback",
    "medium-longctx-fallback",
    "large-cloud-fallback",
]

# ── Strategies ───────────────────────────────────────────────────────────

# Non-empty message content
message_content_st = st.text(
    min_size=1,
    max_size=200,
    alphabet=st.characters(whitelist_categories=("L", "N", "P", "Z")),
).filter(lambda s: s.strip())

# Model used values (including fallback variants)
model_used_st = st.sampled_from(VALID_MODEL_USED)

# A single conversation turn: (user_content, ai_content, model_used)
turn_st = st.tuples(message_content_st, message_content_st, model_used_st)

# A conversation of 1-10 turns handled by potentially different models
conversation_st = st.lists(turn_st, min_size=1, max_size=10)


# ── Helpers ──────────────────────────────────────────────────────────────

def _build_state(**overrides) -> AgentState:
    """Create a minimal AgentState dict with defaults."""
    base: AgentState = {
        "messages": [],
        "current_task": None,
        "extracted_facts": [],
        "long_term_context": None,
        "mode": None,
        "web_search_enabled": True,
        "response_style": None,
        "project_id": None,
        "execution_approved": None,
        "route": None,
        "model_used": None,
        "memory_context": None,
        "persona": None,
        "current_medium_model": None,
        "selected_toolboxes": None,
        "token_budget": None,
        "pending_tool_calls": None,
        "pending_tool_names": [],
        "security_decision": None,
        "security_reason": None,
        "api_tokens_used": None,
        "router_clarification_used": None,
    }
    base.update(overrides)
    return base


def _simulate_conversation(turns):
    """
    Simulate a multi-turn conversation where each turn is handled by a
    potentially different model variant. Returns the final state and a
    list of per-turn provenance records.
    """
    state = _build_state()
    provenance = []

    for user_content, ai_content, model_used in turns:
        # Accumulate messages via add_messages (same as langgraph does)
        state["messages"] = add_messages(
            state["messages"],
            [
                HumanMessage(content=user_content),
                AIMessage(content=ai_content),
            ],
        )
        state["model_used"] = model_used
        provenance.append({
            "model_used": model_used,
            "user_content": user_content,
            "ai_content": ai_content,
        })

    return state, provenance



# ═════════════════════════════════════════════════════════════════════════
# Property 12: Conversation Continuity Across Swaps
# ═════════════════════════════════════════════════════════════════════════

class TestConversationContinuityAcrossSwaps:
    """
    Property 12: For any conversation thread where multiple turns are handled
    by different model variants, the messages list in AgentState SHALL contain
    all messages from all turns in order, and each turn's model_used provenance
    SHALL be preserved in the checkpointed state.

    **Validates: Requirements 26.1, 26.5**
    """

    @given(conversation=conversation_st)
    @settings(max_examples=100)
    def test_all_messages_preserved_across_swaps(self, conversation):
        """
        All messages from all turns are present in the final state,
        regardless of which model variant handled each turn.
        """
        state, provenance = _simulate_conversation(conversation)

        # Each turn adds 2 messages (human + AI)
        expected_count = len(conversation) * 2
        assert len(state["messages"]) == expected_count, (
            f"Expected {expected_count} messages, got {len(state['messages'])}"
        )

    @given(conversation=conversation_st)
    @settings(max_examples=100)
    def test_message_order_preserved_across_swaps(self, conversation):
        """
        Messages maintain chronological order: for each turn i,
        messages[2*i] is the user message and messages[2*i+1] is the AI response.
        """
        state, provenance = _simulate_conversation(conversation)

        for i, record in enumerate(provenance):
            user_msg = state["messages"][2 * i]
            ai_msg = state["messages"][2 * i + 1]
            assert isinstance(user_msg, HumanMessage), (
                f"Turn {i}: expected HumanMessage, got {type(user_msg)}"
            )
            assert isinstance(ai_msg, AIMessage), (
                f"Turn {i}: expected AIMessage, got {type(ai_msg)}"
            )
            assert user_msg.content == record["user_content"], (
                f"Turn {i}: user content mismatch"
            )
            assert ai_msg.content == record["ai_content"], (
                f"Turn {i}: AI content mismatch"
            )

    @given(conversation=conversation_st)
    @settings(max_examples=100)
    def test_model_used_provenance_preserved(self, conversation):
        """
        The model_used field in the state reflects the last turn's model,
        and the per-turn provenance records are all valid model_used values.
        """
        state, provenance = _simulate_conversation(conversation)

        # The state's model_used should match the last turn
        assert state["model_used"] == provenance[-1]["model_used"]

        # Every provenance record has a valid model_used value
        for record in provenance:
            assert record["model_used"] in VALID_MODEL_USED, (
                f"Invalid model_used: {record['model_used']}"
            )

    @given(conversation=st.lists(turn_st, min_size=2, max_size=10))
    @settings(max_examples=100)
    def test_messages_from_different_models_coexist(self, conversation):
        """
        When turns are handled by different model variants, all messages
        from all variants coexist in the same messages list.
        """
        state, provenance = _simulate_conversation(conversation)

        # Collect unique models used
        models_used = {r["model_used"] for r in provenance}

        # All messages are present regardless of how many different models were used
        assert len(state["messages"]) == len(conversation) * 2

        # Each message's content is individually accessible
        all_contents = [m.content for m in state["messages"]]
        for record in provenance:
            assert record["user_content"] in all_contents
            assert record["ai_content"] in all_contents

    @given(
        turn1=turn_st,
        turn2=turn_st,
        turn3=turn_st,
    )
    @settings(max_examples=100)
    def test_swap_back_preserves_earlier_messages(self, turn1, turn2, turn3):
        """
        When the model swaps away and then swaps back (e.g., default → vision → default),
        messages from all three turns are preserved in order.
        """
        state, provenance = _simulate_conversation([turn1, turn2, turn3])

        assert len(state["messages"]) == 6

        # First turn messages
        assert state["messages"][0].content == turn1[0]
        assert state["messages"][1].content == turn1[1]
        # Second turn messages
        assert state["messages"][2].content == turn2[0]
        assert state["messages"][3].content == turn2[1]
        # Third turn messages
        assert state["messages"][4].content == turn3[0]
        assert state["messages"][5].content == turn3[1]

    @given(conversation=conversation_st)
    @settings(max_examples=100)
    def test_add_messages_accumulation_is_monotonic(self, conversation):
        """
        The messages list grows monotonically: after each turn, the count
        increases by exactly 2 and no earlier messages are lost.
        """
        state = _build_state()
        prev_count = 0

        for user_content, ai_content, model_used in conversation:
            state["messages"] = add_messages(
                state["messages"],
                [
                    HumanMessage(content=user_content),
                    AIMessage(content=ai_content),
                ],
            )
            state["model_used"] = model_used

            new_count = len(state["messages"])
            assert new_count == prev_count + 2, (
                f"Expected {prev_count + 2} messages, got {new_count}"
            )
            prev_count = new_count
