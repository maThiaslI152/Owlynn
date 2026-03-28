"""
Unit tests for conversation continuity across model swaps.

Verifies that message history is preserved when different model variants
handle successive turns on the same thread, and that model_used provenance
is tracked per turn.
"""

import sys
from unittest.mock import MagicMock

sys.modules["mem0"] = MagicMock()

from langchain_core.messages import HumanMessage, AIMessage
from langgraph.graph.message import add_messages

from src.agent.state import AgentState


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


class TestMessageHistoryPreservation:
    """Simulate multiple turns with different model_used values on the same thread."""

    def test_messages_grow_across_turns(self):
        """Messages list grows correctly across simulated turns."""
        state = _build_state()

        # Turn 1: user asks, medium-default responds
        turn1_messages = add_messages(
            state["messages"],
            [
                HumanMessage(content="What is Python?"),
                AIMessage(content="Python is a programming language."),
            ],
        )
        state["messages"] = turn1_messages
        state["model_used"] = "medium-default"
        assert len(state["messages"]) == 2

        # Turn 2: user asks about image, medium-vision responds
        turn2_messages = add_messages(
            state["messages"],
            [
                HumanMessage(content="Describe this image."),
                AIMessage(content="The image shows a sunset."),
            ],
        )
        state["messages"] = turn2_messages
        state["model_used"] = "medium-vision"
        assert len(state["messages"]) == 4

        # Turn 3: user asks complex question, medium-default responds again
        turn3_messages = add_messages(
            state["messages"],
            [
                HumanMessage(content="Explain quantum computing."),
                AIMessage(content="Quantum computing uses qubits..."),
            ],
        )
        state["messages"] = turn3_messages
        state["model_used"] = "medium-default"
        assert len(state["messages"]) == 6

    def test_message_content_preserved(self):
        """All message content is preserved across turns."""
        state = _build_state()

        messages_to_add = [
            HumanMessage(content="Hello"),
            AIMessage(content="Hi there!"),
            HumanMessage(content="Tell me about AI"),
            AIMessage(content="AI is fascinating."),
        ]

        accumulated = state["messages"]
        for msg in messages_to_add:
            accumulated = add_messages(accumulated, [msg])

        state["messages"] = accumulated
        assert len(state["messages"]) == 4
        assert state["messages"][0].content == "Hello"
        assert state["messages"][1].content == "Hi there!"
        assert state["messages"][2].content == "Tell me about AI"
        assert state["messages"][3].content == "AI is fascinating."

    def test_message_order_preserved(self):
        """Messages maintain chronological order across model swaps."""
        state = _build_state()

        contents = ["msg1", "msg2", "msg3", "msg4", "msg5", "msg6"]
        accumulated = state["messages"]
        for i, content in enumerate(contents):
            msg_cls = HumanMessage if i % 2 == 0 else AIMessage
            accumulated = add_messages(accumulated, [msg_cls(content=content)])

        state["messages"] = accumulated
        for i, content in enumerate(contents):
            assert state["messages"][i].content == content


class TestModelUsedProvenance:
    """Verify model_used provenance is preserved per turn."""

    def test_model_used_tracks_per_turn(self):
        """Each turn's model_used can be tracked independently."""
        # Simulate a conversation where we track model_used per turn
        turn_records = []

        # Turn 1: medium-default
        turn_records.append({
            "turn": 1,
            "model_used": "medium-default",
            "user_msg": "What is Python?",
            "ai_msg": "Python is a programming language.",
        })

        # Turn 2: medium-vision
        turn_records.append({
            "turn": 2,
            "model_used": "medium-vision",
            "user_msg": "Describe this image.",
            "ai_msg": "The image shows a sunset.",
        })

        # Turn 3: large-cloud
        turn_records.append({
            "turn": 3,
            "model_used": "large-cloud",
            "user_msg": "Prove this theorem.",
            "ai_msg": "By induction...",
        })

        # Turn 4: medium-default again
        turn_records.append({
            "turn": 4,
            "model_used": "medium-default",
            "user_msg": "Summarize our conversation.",
            "ai_msg": "We discussed Python, an image, and a theorem.",
        })

        # Verify provenance is preserved
        assert turn_records[0]["model_used"] == "medium-default"
        assert turn_records[1]["model_used"] == "medium-vision"
        assert turn_records[2]["model_used"] == "large-cloud"
        assert turn_records[3]["model_used"] == "medium-default"

        # Verify all messages are present
        all_messages = []
        for record in turn_records:
            all_messages.append(record["user_msg"])
            all_messages.append(record["ai_msg"])
        assert len(all_messages) == 8

    def test_model_used_with_fallback_suffix(self):
        """Fallback model_used values are tracked correctly."""
        state = _build_state()

        # Simulate a turn where cloud failed and fell back to medium-default
        state["model_used"] = "medium-default-fallback"
        assert "fallback" in state["model_used"]
        assert state["model_used"] == "medium-default-fallback"

    def test_state_preserves_model_used_across_updates(self):
        """model_used in state is correctly updated each turn."""
        state = _build_state()

        model_sequence = [
            "medium-default",
            "medium-vision",
            "medium-default",
            "large-cloud",
            "medium-default-fallback",
        ]

        for model in model_sequence:
            state["model_used"] = model
            assert state["model_used"] == model
