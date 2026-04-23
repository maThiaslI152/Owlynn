"""
Property-based tests for the Redis connection fix in src/agent/graph.py.

Uses Hypothesis to generate inputs and verify properties across the input space.
"""

import sys
from unittest.mock import AsyncMock, MagicMock, patch

# Prevent mem0 import side-effects
sys.modules["mem0"] = MagicMock()

import pytest
from hypothesis import given, settings, assume, HealthCheck
from hypothesis import strategies as st
from langgraph.checkpoint.memory import MemorySaver
from langgraph.checkpoint.base import BaseCheckpointSaver


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

def redis_url_strategy():
    """Generate valid Redis URL formats: redis://host:port"""
    hosts = st.sampled_from([
        "localhost", "127.0.0.1", "redis", "redis-server",
        "my-redis.example.com", "10.0.0.1", "192.168.1.100",
    ])
    ports = st.integers(min_value=1, max_value=65535)
    dbs = st.one_of(st.just(""), st.integers(min_value=0, max_value=15).map(lambda d: f"/{d}"))
    return st.tuples(hosts, ports, dbs).map(
        lambda t: f"redis://{t[0]}:{t[1]}{t[2]}"
    )


def _make_mock_checkpointer(uid: int):
    """Create a uniquely identifiable mock checkpointer that passes LangGraph validation."""
    mock = MagicMock(spec=BaseCheckpointSaver)
    mock._test_uid = uid
    return mock


# ---------------------------------------------------------------------------
# 7.1 [PBT: Exploration] — Surface the original bug as a counterexample
#
# The ORIGINAL buggy code tried two import paths:
#   1. from langgraph.checkpoint.redis import AsyncRedisSaver  (used url= kwarg)
#   2. from langgraph_checkpoint_redis import AsyncRedisSaver   (used url= kwarg)
#
# Both failed. This test simulates the ORIGINAL buggy import+constructor
# logic and asserts success. Since the original logic was broken, the test
# should FAIL — that failure IS the counterexample proving the bug.
#
# **Validates: Requirements 1.1, 1.2, 1.3**
# ---------------------------------------------------------------------------

class TestExplorationBugCondition:
    """PBT Exploration: Demonstrate the original bug via counterexample."""

    @given(redis_url=redis_url_strategy())
    @settings(
        max_examples=20,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
        deadline=None,
    )
    def test_original_buggy_import_paths_fail(self, redis_url: str):
        """
        Simulate the ORIGINAL (pre-fix) import logic:
        - Try `from langgraph_checkpoint_redis import AsyncRedisSaver`
          and construct with `AsyncRedisSaver(url=redis_url)`
        - Assert at least one path succeeds.

        This SHOULD FAIL because the legacy import path does not exist
        and the original code used the wrong constructor kwarg (`url=`
        instead of `redis_url=`). The failure is the counterexample
        proving the bug.

        **Validates: Requirements 1.1, 1.2**
        """
        success = False

        # Attempt 1: the legacy standalone module (original buggy path)
        try:
            from langgraph_checkpoint_redis import AsyncRedisSaver as LegacySaver
            # Original code used url= kwarg (also buggy)
            _checkpointer = LegacySaver(url=redis_url)
            success = True
        except (ImportError, ModuleNotFoundError, TypeError):
            pass

        # Attempt 2: simulate the original primary path with wrong constructor
        # The original code did: AsyncRedisSaver(url=REDIS_URL) — wrong kwarg
        # We test that using `url=` (the buggy kwarg) on the real class fails
        if not success:
            try:
                from langgraph.checkpoint.redis import AsyncRedisSaver
                # Use the BUGGY constructor kwarg `url=` (should be `redis_url=`)
                _checkpointer = AsyncRedisSaver(url=redis_url)
                success = True
            except (ImportError, ModuleNotFoundError, TypeError):
                pass

        assert success, (
            f"Bug confirmed: neither original import path with url= kwarg "
            f"succeeded for redis_url={redis_url!r}. "
            f"Legacy import 'langgraph_checkpoint_redis' is missing, and "
            f"the constructor kwarg 'url=' is incorrect (should be 'redis_url=')."
        )


# ---------------------------------------------------------------------------
# 7.2 [PBT: Fix] — For any valid REDIS_URL, init_agent() creates a
#     Redis-backed checkpointer (not MemorySaver) when Redis is reachable
#
# **Validates: Requirements 2.1, 2.2**
# ---------------------------------------------------------------------------

class TestFixRedisCheckpointer:
    """PBT Fix: Verify the fixed init_agent() uses Redis for any valid URL."""

    @given(redis_url=redis_url_strategy())
    @settings(
        max_examples=30,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
        deadline=None,
    )
    @pytest.mark.asyncio
    async def test_init_agent_creates_redis_checkpointer(self, redis_url: str):
        """
        For any valid REDIS_URL format, init_agent() should create a
        Redis-backed checkpointer (not MemorySaver) when the Redis
        connection succeeds.

        We mock the Redis connection (asetup) to simulate reachability,
        but verify the checkpointer type is NOT MemorySaver.

        **Validates: Requirements 2.1, 2.2**
        """
        from src.agent.graph import init_agent

        mock_asetup = AsyncMock()

        with (
            patch("src.config.settings.REDIS_URL", redis_url),
            patch("src.agent.graph.REDIS_URL", redis_url),
            patch(
                "src.agent.graph.mcp_manager.initialize",
                new_callable=AsyncMock,
            ),
            patch(
                "langgraph.checkpoint.redis.aio.AsyncRedisSaver.asetup",
                mock_asetup,
            ),
        ):
            graph = await init_agent()

        assert not isinstance(graph.checkpointer, MemorySaver), (
            f"Expected Redis-backed checkpointer for url={redis_url!r}, "
            f"but got MemorySaver. The fix should use AsyncRedisSaver."
        )


# ---------------------------------------------------------------------------
# 7.3 [PBT: Preservation] — For any explicit checkpointer passed to
#     init_agent(), the returned graph uses that exact checkpointer
#
# **Validates: Requirements 3.1, 3.2**
# ---------------------------------------------------------------------------

class TestPreservationCheckpointerPassthrough:
    """PBT Preservation: Explicit checkpointer passthrough is preserved."""

    @given(data=st.data())
    @settings(
        max_examples=30,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
        deadline=None,
    )
    @pytest.mark.asyncio
    async def test_explicit_checkpointer_used_as_is(self, data):
        """
        For any explicit checkpointer passed to init_agent(), the returned
        graph must use that exact checkpointer object — no Redis init
        should be attempted.

        **Validates: Requirements 3.1, 3.2**
        """
        from src.agent.graph import init_agent

        uid = data.draw(st.integers(min_value=0, max_value=10000))
        mock_checkpointer = _make_mock_checkpointer(uid)

        with patch(
            "src.agent.graph.mcp_manager.initialize",
            new_callable=AsyncMock,
        ):
            graph = await init_agent(checkpointer=mock_checkpointer)

        assert graph.checkpointer is mock_checkpointer, (
            f"Expected the exact checkpointer (uid={uid}) to be used, "
            f"but got {type(graph.checkpointer).__name__}. "
            f"Passthrough behavior must be preserved."
        )
        assert graph.checkpointer._test_uid == uid, (
            f"Checkpointer identity mismatch: expected uid={uid}, "
            f"got uid={graph.checkpointer._test_uid}"
        )
