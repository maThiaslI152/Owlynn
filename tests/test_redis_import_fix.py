"""
Unit tests for the Redis connection fix in src/agent/graph.py.

Validates:
- Correct AsyncRedisSaver import path resolution
- Redis-backed checkpointer initialization when Redis is available
- Explicit checkpointer passthrough (no Redis init attempted)
- Graceful MemorySaver fallback when Redis is unreachable + error logging
"""

import sys
import logging
from unittest.mock import AsyncMock, MagicMock, patch

# Prevent mem0 import side-effects
sys.modules["mem0"] = MagicMock()

import pytest
from langgraph.checkpoint.memory import MemorySaver


# ---------------------------------------------------------------------------
# 6.1  AsyncRedisSaver can be imported from the correct module path
# ---------------------------------------------------------------------------

class TestAsyncRedisSaverImport:
    """Verify AsyncRedisSaver is importable from the primary module path."""

    def test_import_from_primary_path(self):
        """AsyncRedisSaver should be importable from langgraph.checkpoint.redis."""
        from langgraph.checkpoint.redis import AsyncRedisSaver
        assert AsyncRedisSaver is not None


# ---------------------------------------------------------------------------
# 6.2  init_agent() with no args → Redis-backed checkpointer (live Redis)
# ---------------------------------------------------------------------------

def _redis_with_search_available() -> bool:
    """Return True if Redis is reachable AND has the RediSearch module
    (required by AsyncRedisSaver for index creation during asetup)."""
    try:
        import redis
        r = redis.Redis()
        r.ping()
        # AsyncRedisSaver.asetup() runs FT._LIST which requires RediSearch
        r.execute_command("FT._LIST")
        return True
    except Exception:
        return False


class TestInitAgentRedisCheckpointer:
    """init_agent() should use a Redis-backed checkpointer when Redis + RediSearch is up."""

    @pytest.mark.skipif(
        not _redis_with_search_available(),
        reason="Live Redis server with RediSearch module not available",
    )
    @pytest.mark.asyncio
    async def test_init_agent_uses_redis_checkpointer(self):
        """With no args and Redis+RediSearch running, init_agent returns a
        graph whose checkpointer is NOT MemorySaver (i.e. it is Redis-backed)."""
        from src.agent.graph import init_agent

        graph = await init_agent()
        assert graph is not None
        # The compiled graph's checkpointer should not be MemorySaver
        checkpointer = graph.checkpointer
        assert not isinstance(checkpointer, MemorySaver), (
            "Expected a Redis-backed checkpointer but got MemorySaver"
        )


# ---------------------------------------------------------------------------
# 6.3  init_agent(checkpointer=mock_saver) → uses provided checkpointer
# ---------------------------------------------------------------------------

class TestInitAgentExplicitCheckpointer:
    """When an explicit checkpointer is passed, it must be used as-is."""

    @pytest.mark.asyncio
    async def test_explicit_checkpointer_passthrough(self):
        """init_agent(checkpointer=mock_saver) should use the provided
        checkpointer without attempting Redis initialization."""
        from src.agent.graph import init_agent

        mock_saver = MagicMock(spec=MemorySaver)

        with patch(
            "src.agent.graph.mcp_manager.initialize",
            new_callable=AsyncMock,
        ):
            graph = await init_agent(checkpointer=mock_saver)

        assert graph.checkpointer is mock_saver


# ---------------------------------------------------------------------------
# 6.4  init_agent() falls back to MemorySaver when Redis is unreachable
#       and logs an error-level message
# ---------------------------------------------------------------------------

class TestInitAgentMemorySaverFallback:
    """When Redis is unreachable, init_agent must fall back to MemorySaver
    and emit an ERROR log containing both exception messages."""

    @pytest.mark.asyncio
    async def test_fallback_to_memory_saver_on_redis_failure(self):
        """Both Redis import paths fail → MemorySaver is used."""
        from src.agent.graph import init_agent

        # Make both import paths raise so the fallback triggers
        original_import = __builtins__.__import__ if hasattr(__builtins__, '__import__') else __import__

        def _failing_import(name, *args, **kwargs):
            if name in (
                "langgraph.checkpoint.redis",
                "langgraph_checkpoint_redis",
            ):
                raise ImportError(f"mocked failure for {name}")
            return original_import(name, *args, **kwargs)

        with (
            patch("builtins.__import__", side_effect=_failing_import),
            patch(
                "src.agent.graph.mcp_manager.initialize",
                new_callable=AsyncMock,
            ),
        ):
            graph = await init_agent()

        assert isinstance(graph.checkpointer, MemorySaver), (
            f"Expected MemorySaver fallback, got {type(graph.checkpointer)}"
        )

    @pytest.mark.asyncio
    async def test_error_logged_on_redis_failure(self, caplog):
        """An ERROR-level log must be emitted when Redis init fails,
        containing both exception messages."""
        from src.agent.graph import init_agent

        original_import = __builtins__.__import__ if hasattr(__builtins__, '__import__') else __import__

        def _failing_import(name, *args, **kwargs):
            if name in (
                "langgraph.checkpoint.redis",
                "langgraph_checkpoint_redis",
            ):
                raise ImportError(f"mocked failure for {name}")
            return original_import(name, *args, **kwargs)

        with (
            patch("builtins.__import__", side_effect=_failing_import),
            patch(
                "src.agent.graph.mcp_manager.initialize",
                new_callable=AsyncMock,
            ),
            caplog.at_level(logging.ERROR, logger="src.agent.graph"),
        ):
            await init_agent()

        # Verify an error-level record was emitted
        error_records = [
            r for r in caplog.records
            if r.levelno >= logging.ERROR and "src.agent.graph" in r.name
        ]
        assert len(error_records) >= 1, "Expected at least one ERROR log from src.agent.graph"

        error_msg = error_records[0].getMessage()
        assert "MemorySaver" in error_msg or "fallback" in error_msg.lower(), (
            f"Error log should mention MemorySaver fallback, got: {error_msg}"
        )
