"""
Unit tests for the Memory Nodes (memory_inject_node, memory_write_node).

Tests memory context building, cache behavior, Mem0 interaction,
profile/persona injection, and conversation recording.
"""

import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from datetime import datetime, timedelta

from src.agent.nodes.memory import (
    memory_inject_node,
    memory_write_node,
    format_memory_context,
    MemoryContextCache,
    _get_mem0_user_id,
)


# ── Fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def clear_cache():
    """Clear the MemoryContextCache between tests."""
    MemoryContextCache._cache.clear()
    yield


@pytest.fixture
def mock_personal_assistant():
    """Mock the personal_assistant module to avoid filesystem dependencies."""
    with patch("src.agent.nodes.memory.TopicExtractor") as mock_te, \
         patch("src.agent.nodes.memory.MemoryEnricher") as mock_me, \
         patch("src.agent.nodes.memory.record_conversation") as mock_rc, \
         patch("src.agent.nodes.memory.get_memory_context_for_prompt", return_value="Enhanced context") as mock_gmc, \
         patch("src.agent.nodes.memory.get_user_interests_summary", return_value="Interests summary") as mock_gui:
        mock_te.extract_topics = MagicMock(return_value=["tech", "python"])
        mock_te.extract_interests = MagicMock(return_value=["coding"])
        mock_me.enrich_memory = MagicMock(return_value="Enriched: user asked about python")
        yield {
            "extract_topics": mock_te.extract_topics,
            "extract_interests": mock_te.extract_interests,
            "enrich_memory": mock_me.enrich_memory,
            "record_conversation": mock_rc,
            "get_memory_context": mock_gmc,
        }


@pytest.fixture
def mock_profile():
    """Mock the user profile."""
    with patch("src.agent.nodes.memory.get_profile") as mock:
        mock.return_value = {
            "name": "TestUser",
            "email": "test@example.com",
            "preferred_language": "English",
            "llm_base_url": "http://localhost:1234",  # Should be filtered out
        }
        yield mock


@pytest.fixture
def mock_persona():
    """Mock the persona."""
    with patch("src.agent.nodes.memory.get_persona") as mock:
        mock.return_value = {
            "role": "helpful assistant",
            "system_prompt": "You are helpful.",
        }
        yield mock


def _make_state(messages=None, thread_id="test_thread_1", project_id=None, **extra):
    """Build a minimal AgentState dict."""
    return {
        "messages": messages or [],
        "thread_id": thread_id,
        "project_id": project_id or "default",
        **extra,
    }


def _human_msg(content: str):
    """Create a mock human message."""
    msg = MagicMock()
    msg.type = "human"
    msg.content = content
    return msg


def _ai_msg(content: str):
    """Create a mock AI message."""
    msg = MagicMock()
    msg.type = "ai"
    msg.content = content
    return msg


# ── _get_mem0_user_id ──────────────────────────────────────────────────────

class TestGetMem0UserId:
    def test_default_project_uses_profile_name(self):
        with patch("src.agent.nodes.memory.get_profile") as mock:
            mock.return_value = {"name": "Alice"}
            state = _make_state(project_id="default")
            uid = _get_mem0_user_id(state)
            assert uid == "Alice"

    def test_default_project_falls_back_to_owner(self):
        with patch("src.agent.nodes.memory.get_profile") as mock:
            mock.return_value = {"name": ""}
            state = _make_state(project_id="default")
            uid = _get_mem0_user_id(state)
            assert uid == "owner"

    def test_non_default_project_uses_project_prefix(self):
        state = _make_state(project_id="my-project")
        uid = _get_mem0_user_id(state)
        assert uid == "project:my-project"

    def test_exception_falls_back_to_owner(self):
        with patch("src.agent.nodes.memory.get_profile", side_effect=Exception("DB error")):
            state = _make_state(project_id="default")
            uid = _get_mem0_user_id(state)
            assert uid == "owner"


# ── format_memory_context ──────────────────────────────────────────────────

class TestFormatMemoryContext:
    def test_no_data_returns_fallback(self):
        result = format_memory_context([], {}, "", "")
        assert result == "No prior memory available."

    def test_user_profile_fields_filtered(self):
        profile = {
            "name": "Alice",
            "email": "alice@test.com",
            "llm_base_url": "http://localhost:1234",  # Should be filtered
            "system_prompt": "hidden",  # Should be filtered
        }
        result = format_memory_context([], profile, "", "")
        assert "name: Alice" in result
        assert "email" in result
        assert "llm_base_url" not in result
        assert "system_prompt" not in result

    def test_project_instructions_included(self):
        result = format_memory_context([], {}, "", "Follow these rules.")
        assert "ACTIVE PROJECT CONTEXT" in result
        assert "Follow these rules." in result

    def test_enhanced_context_included(self):
        result = format_memory_context([], {}, "Enhanced context here", "")
        assert "Your Knowledge About User" in result
        assert "Enhanced context here" in result

    def test_relevant_past_context_included(self):
        results = [{"memory": "User likes Python"}, {"memory": "User works on AI projects"}]
        result = format_memory_context(results, {}, "", "")
        assert "Relevant Past Context" in result
        assert "User likes Python" in result


# ── MemoryContextCache ─────────────────────────────────────────────────────

class TestMemoryContextCache:
    def test_set_and_get(self):
        MemoryContextCache.set("thread_1", "cached context")
        assert MemoryContextCache.get("thread_1") == "cached context"

    def test_cache_miss_returns_none(self):
        assert MemoryContextCache.get("nonexistent") is None

    def test_cache_expires(self):
        original_ttl = MemoryContextCache._ttl_seconds
        MemoryContextCache._ttl_seconds = -1  # Force immediate expiry
        MemoryContextCache.set("thread_1", "old context")
        assert MemoryContextCache.get("thread_1") is None
        MemoryContextCache._ttl_seconds = original_ttl  # Restore

    def test_invalidate_removes_entry(self):
        MemoryContextCache.set("thread_1", "some context")
        MemoryContextCache.invalidate("thread_1")
        assert MemoryContextCache.get("thread_1") is None

    def test_invalidate_on_write_returns_true(self):
        MemoryContextCache.set("thread_1", "some context")
        result = MemoryContextCache.invalidate_on_write("thread_1")
        assert result is True
        assert MemoryContextCache.get("thread_1") is None


# ── memory_inject_node ─────────────────────────────────────────────────────

class TestMemoryInjectNode:
    @patch("src.memory.long_term.memory", None)  # No Mem0 available
    @pytest.mark.asyncio
    async def test_no_mem0_uses_json_memory(self, mock_personal_assistant, mock_profile, mock_persona):
        """When Mem0 is unavailable, the node still builds context from profile/persona."""
        state = _make_state(messages=[_human_msg("Hello")])
        result = await memory_inject_node(state)
        assert "memory_context" in result
        assert result["persona"] == "helpful assistant"
        assert "TestUser" in str(result["memory_context"])

    @pytest.mark.asyncio
    async def test_cache_hit_skips_profile_and_persona_lookup(self, mock_persona):
        """When the cache is populated, we return cached context + persona."""
        # Use minimal mocks for the cache-hit path
        with patch("src.agent.nodes.memory.get_profile") as mock_prof:
            mock_prof.return_value = {"name": "TestUser"}
            # Clear and set cache manually
            MemoryContextCache._cache.clear()
            MemoryContextCache.set("test_thread_1", "cached value")
            state = _make_state(messages=[_human_msg("Hello")])
            # Debug: verify cache is set
            cached = MemoryContextCache.get("test_thread_1")
            assert cached == "cached value", f"Cache should contain 'cached value', got: {cached!r}"
            mock_prof.reset_mock()
            result = await memory_inject_node(state)
            assert result["memory_context"] == "cached value"
            # Profile should NOT be re-fetched on cache hit
            mock_prof.assert_not_called()
            # Persona IS still fetched on cache hit (by design)
            mock_persona.assert_called_once()

    @pytest.mark.asyncio
    async def test_cache_populated_on_miss(self, mock_personal_assistant, mock_profile, mock_persona):
        """After a cache miss, the context is stored in the cache."""
        with patch("src.memory.long_term.memory", None):
            state = _make_state(messages=[_human_msg("Hello")])
            assert MemoryContextCache.get("test_thread_1") is None
            result = await memory_inject_node(state)
            # The cache should have been populated by memory_inject_node
            # Use MemoryContextCache._cache directly to verify
            assert "test_thread_1" in MemoryContextCache._cache, (
                f"Cache should have key 'test_thread_1'. Keys: {list(MemoryContextCache._cache.keys())}"
            )
            cached_entry = MemoryContextCache._cache.get("test_thread_1")
            cached_text = cached_entry[1] if cached_entry else None
            assert cached_text == result["memory_context"], (
                f"Cached text {cached_text!r} != result {result['memory_context']!r}"
            )


# ── memory_write_node ──────────────────────────────────────────────────────

class TestMemoryWriteNode:
    @pytest.mark.asyncio
    async def test_no_messages_returns_empty(self, mock_personal_assistant):
        """With no messages, the node does nothing."""
        state = _make_state(messages=[])
        result = await memory_write_node(state)
        assert result == {}

    @pytest.mark.asyncio
    async def test_missing_human_message_returns_empty(self, mock_personal_assistant):
        """Without a human message, the node does nothing."""
        state = _make_state(messages=[_ai_msg("Hello")])
        result = await memory_write_node(state)
        assert result == {}

    @pytest.mark.asyncio
    async def test_records_conversation(self, mock_personal_assistant):
        """With human+AI messages, conversation is recorded."""
        state = _make_state(
            messages=[_human_msg("What is Python?"), _ai_msg("Python is a programming language.")],
            session_id="sess_1",
        )
        result = await memory_write_node(state)
        assert mock_personal_assistant["record_conversation"].called
        assert result.get("memory_invalidated") is True

    @patch("src.memory.long_term.memory", None)
    @pytest.mark.asyncio
    async def test_no_mem0_still_records_conversation(self, mock_personal_assistant):
        """When Mem0 is unavailable, conversation is still recorded to JSON."""
        state = _make_state(
            messages=[_human_msg("What is Python?"), _ai_msg("Python is a language.")],
        )
        result = await memory_write_node(state)
        assert mock_personal_assistant["record_conversation"].called
        assert result.get("memory_invalidated") is True

    @patch("src.memory.long_term.memory")
    @pytest.mark.asyncio
    async def test_saves_fact_to_mem0(self, mock_mem0, mock_personal_assistant):
        """When Mem0 is available, enriched facts are saved."""
        mock_mem0.add = MagicMock()
        state = _make_state(
            messages=[_human_msg("Tell me about Rust"), _ai_msg("Rust is a systems language.")],
        )
        result = await memory_write_node(state)
        mock_mem0.add.assert_called_once()
        call_kwargs = mock_mem0.add.call_args[1]
        assert call_kwargs["user_id"] is not None
        assert call_kwargs["infer"] is False
        assert result.get("memory_invalidated") is True

    @pytest.mark.asyncio
    async def test_extracts_topics_and_interests(self, mock_personal_assistant):
        """Topics and interests are extracted and used in enriched fact."""
        state = _make_state(
            messages=[_human_msg("I love coding in Python"), _ai_msg("Python is great for AI.")],
        )
        await memory_write_node(state)
        mock_personal_assistant["extract_topics"].assert_called_once()
        mock_personal_assistant["extract_interests"].assert_called_once()
        mock_personal_assistant["enrich_memory"].assert_called_once()

    @pytest.mark.asyncio
    async def test_cache_invalidated_on_write(self, mock_personal_assistant):
        """Memory cache is invalidated after writing new memories."""
        MemoryContextCache.set("test_thread_1", "old context")
        state = _make_state(
            messages=[_human_msg("Hello"), _ai_msg("Hi there!")],
        )
        # Mock memory to avoid DB connection errors
        with patch("src.memory.long_term.memory") as mock_mem:
            mock_mem.add = MagicMock()
            await memory_write_node(state)
        assert MemoryContextCache.get("test_thread_1") is None
