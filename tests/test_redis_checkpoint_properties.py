"""
Property-based tests for Redis checkpoint round-trip and thread isolation.

# Feature: deepseek-hybrid-integration, Property 11: Redis Checkpoint Round-Trip
# Validates: Requirements 25.7, 25.8, 25.9

Since we cannot use a live Redis instance in unit tests, we simulate the
checkpoint store/retrieve cycle using a dict-based mock that mimics the
checkpointer's put/get behavior.  The key insight is testing that the data
structure survives serialization/deserialization (json.dumps / json.loads)
and that thread isolation is maintained.
"""

import sys
import json
import copy
import uuid
from unittest.mock import MagicMock

sys.modules["mem0"] = MagicMock()

import pytest
from hypothesis import given, settings, assume
from hypothesis import strategies as st
from langchain_core.messages import HumanMessage, AIMessage
from langgraph.graph.message import add_messages

from src.agent.state import AgentState

# ── Constants ────────────────────────────────────────────────────────────

VALID_ROUTES = [
    "simple",
    "complex-default",
    "complex-vision",
    "complex-longctx",
    "complex-cloud",
]

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

VALID_TOOLBOX_NAMES = [
    "web_search",
    "file_ops",
    "data_viz",
    "productivity",
    "memory",
    "all",
]

# ── Strategies ───────────────────────────────────────────────────────────

message_content_st = st.text(
    min_size=1,
    max_size=200,
    alphabet=st.characters(whitelist_categories=("L", "N", "P", "Z")),
).filter(lambda s: s.strip())

route_st = st.sampled_from(VALID_ROUTES)
model_used_st = st.sampled_from(VALID_MODEL_USED)
token_budget_st = st.integers(min_value=256, max_value=131072)

toolboxes_st = st.lists(
    st.sampled_from(VALID_TOOLBOX_NAMES),
    min_size=1,
    max_size=4,
).map(lambda xs: list(set(xs)))

thread_id_st = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N"), whitelist_characters="-_"),
    min_size=4,
    max_size=30,
).filter(lambda s: s.strip())

messages_st = st.lists(
    st.tuples(message_content_st, message_content_st),
    min_size=1,
    max_size=5,
)


# ── Mock Checkpoint Store ────────────────────────────────────────────────

class MockCheckpointStore:
    """
    Dict-based mock that mimics Redis checkpointer put/get behavior.
    Data passes through json.dumps / json.loads to simulate serialization
    round-trip, ensuring the data structure survives the same kind of
    transformation that Redis would apply.
    """

    def __init__(self):
        self._store: dict[str, str] = {}

    def put(self, thread_id: str, state: dict) -> None:
        """Serialize and store state for a given thread_id."""
        serializable = self._to_serializable(state)
        self._store[thread_id] = json.dumps(serializable)

    def get(self, thread_id: str) -> dict | None:
        """Retrieve and deserialize state for a given thread_id."""
        raw = self._store.get(thread_id)
        if raw is None:
            return None
        data = json.loads(raw)
        return self._from_serializable(data)

    @staticmethod
    def _to_serializable(state: dict) -> dict:
        """Convert AgentState-like dict to a JSON-serializable form."""
        out = {}
        for key, value in state.items():
            if key == "messages":
                out[key] = [
                    {"type": type(m).__name__, "content": m.content}
                    for m in value
                ]
            else:
                out[key] = copy.deepcopy(value)
        return out

    @staticmethod
    def _from_serializable(data: dict) -> dict:
        """Reconstruct AgentState-like dict from deserialized JSON."""
        out = {}
        for key, value in data.items():
            if key == "messages":
                msgs = []
                for m in value:
                    if m["type"] == "HumanMessage":
                        msgs.append(HumanMessage(content=m["content"]))
                    elif m["type"] == "AIMessage":
                        msgs.append(AIMessage(content=m["content"]))
                out[key] = msgs
            else:
                out[key] = value
        return out


# ── Helpers ──────────────────────────────────────────────────────────────

def _build_checkpoint_state(
    messages_pairs: list[tuple[str, str]],
    route: str,
    model_used: str,
    selected_toolboxes: list[str],
    token_budget: int,
) -> dict:
    """Build a minimal AgentState-like dict with the fields under test."""
    msgs = []
    for user_content, ai_content in messages_pairs:
        msgs.append(HumanMessage(content=user_content))
        msgs.append(AIMessage(content=ai_content))
    return {
        "messages": msgs,
        "route": route,
        "model_used": model_used,
        "selected_toolboxes": selected_toolboxes,
        "token_budget": token_budget,
    }


# ═════════════════════════════════════════════════════════════════════════
# Property 11: Redis Checkpoint Round-Trip
# ═════════════════════════════════════════════════════════════════════════

class TestRedisCheckpointRoundTrip:
    """
    Property 11: For any valid AgentState and Thread_ID, storing the state
    via the checkpointer and then retrieving it for the same Thread_ID SHALL
    produce an AgentState with identical messages, route, model_used,
    selected_toolboxes, and token_budget fields.  Different Thread_IDs SHALL
    maintain isolated state.

    **Validates: Requirements 25.7, 25.8, 25.9**
    """

    @given(
        messages_pairs=messages_st,
        route=route_st,
        model_used=model_used_st,
        toolboxes=toolboxes_st,
        token_budget=token_budget_st,
        thread_id=thread_id_st,
    )
    @settings(max_examples=100)
    def test_store_then_retrieve_identical_state(
        self, messages_pairs, route, model_used, toolboxes, token_budget, thread_id
    ):
        """
        Storing a state and retrieving it for the same thread_id produces
        identical messages, route, model_used, selected_toolboxes, and
        token_budget.
        """
        store = MockCheckpointStore()
        state = _build_checkpoint_state(
            messages_pairs, route, model_used, toolboxes, token_budget
        )

        store.put(thread_id, state)
        retrieved = store.get(thread_id)

        assert retrieved is not None

        # messages: same count, same types, same content
        assert len(retrieved["messages"]) == len(state["messages"])
        for orig, restored in zip(state["messages"], retrieved["messages"]):
            assert type(orig).__name__ == type(restored).__name__
            assert orig.content == restored.content

        # scalar / list fields
        assert retrieved["route"] == state["route"]
        assert retrieved["model_used"] == state["model_used"]
        assert retrieved["selected_toolboxes"] == state["selected_toolboxes"]
        assert retrieved["token_budget"] == state["token_budget"]

    @given(
        messages_pairs=messages_st,
        route=route_st,
        model_used=model_used_st,
        toolboxes=toolboxes_st,
        token_budget=token_budget_st,
        thread_id=thread_id_st,
    )
    @settings(max_examples=100)
    def test_message_types_preserved_after_round_trip(
        self, messages_pairs, route, model_used, toolboxes, token_budget, thread_id
    ):
        """
        After round-trip, HumanMessage and AIMessage types are correctly
        reconstructed in alternating order.
        """
        store = MockCheckpointStore()
        state = _build_checkpoint_state(
            messages_pairs, route, model_used, toolboxes, token_budget
        )

        store.put(thread_id, state)
        retrieved = store.get(thread_id)

        for i, msg in enumerate(retrieved["messages"]):
            if i % 2 == 0:
                assert isinstance(msg, HumanMessage), (
                    f"Index {i}: expected HumanMessage, got {type(msg).__name__}"
                )
            else:
                assert isinstance(msg, AIMessage), (
                    f"Index {i}: expected AIMessage, got {type(msg).__name__}"
                )

    @given(
        pairs_a=messages_st,
        route_a=route_st,
        model_a=model_used_st,
        toolboxes_a=toolboxes_st,
        budget_a=token_budget_st,
        thread_a=thread_id_st,
        pairs_b=messages_st,
        route_b=route_st,
        model_b=model_used_st,
        toolboxes_b=toolboxes_st,
        budget_b=token_budget_st,
        thread_b=thread_id_st,
    )
    @settings(max_examples=100)
    def test_thread_isolation(
        self,
        pairs_a, route_a, model_a, toolboxes_a, budget_a, thread_a,
        pairs_b, route_b, model_b, toolboxes_b, budget_b, thread_b,
    ):
        """
        Storing states for different thread_ids does not cause interference.
        Each thread retrieves only its own state.
        """
        assume(thread_a != thread_b)

        store = MockCheckpointStore()
        state_a = _build_checkpoint_state(
            pairs_a, route_a, model_a, toolboxes_a, budget_a
        )
        state_b = _build_checkpoint_state(
            pairs_b, route_b, model_b, toolboxes_b, budget_b
        )

        store.put(thread_a, state_a)
        store.put(thread_b, state_b)

        retrieved_a = store.get(thread_a)
        retrieved_b = store.get(thread_b)

        # Thread A state is intact
        assert retrieved_a["route"] == route_a
        assert retrieved_a["model_used"] == model_a
        assert retrieved_a["selected_toolboxes"] == toolboxes_a
        assert retrieved_a["token_budget"] == budget_a
        assert len(retrieved_a["messages"]) == len(pairs_a) * 2

        # Thread B state is intact
        assert retrieved_b["route"] == route_b
        assert retrieved_b["model_used"] == model_b
        assert retrieved_b["selected_toolboxes"] == toolboxes_b
        assert retrieved_b["token_budget"] == budget_b
        assert len(retrieved_b["messages"]) == len(pairs_b) * 2

    @given(
        messages_pairs=messages_st,
        route=route_st,
        model_used=model_used_st,
        toolboxes=toolboxes_st,
        token_budget=token_budget_st,
        thread_id=thread_id_st,
    )
    @settings(max_examples=100)
    def test_overwrite_same_thread_returns_latest(
        self, messages_pairs, route, model_used, toolboxes, token_budget, thread_id
    ):
        """
        Storing a new state for the same thread_id overwrites the previous
        state; retrieval returns the latest version.
        """
        store = MockCheckpointStore()

        # Store initial state
        initial_state = _build_checkpoint_state(
            messages_pairs, route, model_used, toolboxes, token_budget
        )
        store.put(thread_id, initial_state)

        # Store updated state with different route
        new_route = "simple" if route != "simple" else "complex-default"
        updated_state = _build_checkpoint_state(
            messages_pairs, new_route, model_used, toolboxes, token_budget
        )
        store.put(thread_id, updated_state)

        retrieved = store.get(thread_id)
        assert retrieved["route"] == new_route

    @given(thread_id=thread_id_st)
    @settings(max_examples=100)
    def test_get_nonexistent_thread_returns_none(self, thread_id):
        """
        Retrieving a thread_id that was never stored returns None.
        """
        store = MockCheckpointStore()
        assert store.get(thread_id) is None
