#!/usr/bin/env python3
"""
Standalone test: Redis checkpointer round-trip and thread isolation.

NOT a pytest module — run directly:
    python tests/standalone/test_redis_checkpointer.py

Requires a live Redis instance at localhost:6379.
"""

import asyncio
import sys
import os
import uuid

# Ensure project root is on sys.path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))


async def main():
    # Mirror the same import order as init_agent() in src/agent/graph.py
    AsyncRedisSaver = None
    import_style = None
    errors = []

    # 1) Primary: langgraph.checkpoint.redis (newer package versions)
    try:
        from langgraph.checkpoint.redis import AsyncRedisSaver as _PrimarySaver
        AsyncRedisSaver = _PrimarySaver
        import_style = "primary"
        print("OK: Imported AsyncRedisSaver via langgraph.checkpoint.redis")
    except Exception as e:
        errors.append(f"  langgraph.checkpoint.redis → {type(e).__name__}: {e}")

    # 2) Legacy fallback: langgraph_checkpoint_redis (older package versions)
    if AsyncRedisSaver is None:
        try:
            from langgraph_checkpoint_redis import AsyncRedisSaver as _LegacySaver
            AsyncRedisSaver = _LegacySaver
            import_style = "legacy"
            print("OK: Imported AsyncRedisSaver via langgraph_checkpoint_redis (legacy)")
        except Exception as e:
            errors.append(f"  langgraph_checkpoint_redis → {type(e).__name__}: {e}")

    if AsyncRedisSaver is None:
        print("FAIL: Could not import AsyncRedisSaver from any known path.")
        print("Tried the following import paths (same order as init_agent()):")
        for err in errors:
            print(err)
        sys.exit(1)

    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")
    print(f"Connecting to Redis at {redis_url} ...")

    try:
        if import_style == "primary":
            checkpointer = AsyncRedisSaver(redis_url=redis_url)
            await checkpointer.asetup()
        else:
            checkpointer = AsyncRedisSaver(url=redis_url)
            await checkpointer.setup()
        print("OK: Connected and setup complete.")
    except Exception as e:
        print(f"SKIP: Cannot connect to Redis — {e}")
        sys.exit(0)

    # ── Test 1: Store and retrieve a checkpoint ──────────────────────────
    thread_id_1 = f"test-thread-{uuid.uuid4().hex[:8]}"
    config_1 = {"configurable": {"thread_id": thread_id_1}}

    # Build a minimal checkpoint
    checkpoint_1 = {
        "v": 1,
        "id": str(uuid.uuid4()),
        "ts": "2025-01-01T00:00:00+00:00",
        "channel_values": {
            "messages": [
                {"type": "human", "content": "Hello from test"},
                {"type": "ai", "content": "Hi! I'm a test response."},
            ],
            "route": "complex-default",
            "model_used": "medium-default",
        },
        "channel_versions": {},
        "versions_seen": {},
        "pending_sends": [],
    }

    try:
        await checkpointer.aput(config_1, checkpoint_1, {}, {})
        print(f"OK: Stored checkpoint for thread {thread_id_1}")
    except Exception as e:
        print(f"FAIL: Could not store checkpoint — {e}")
        sys.exit(1)

    # Retrieve
    try:
        retrieved = await checkpointer.aget_tuple(config_1)
        if retrieved is None:
            print("FAIL: Retrieved checkpoint is None")
            sys.exit(1)

        stored_values = retrieved.checkpoint.get("channel_values", {})
        assert stored_values.get("route") == "complex-default", \
            f"Route mismatch: {stored_values.get('route')}"
        assert stored_values.get("model_used") == "medium-default", \
            f"model_used mismatch: {stored_values.get('model_used')}"
        print("OK: Retrieved checkpoint matches stored state.")
    except Exception as e:
        print(f"FAIL: Checkpoint retrieval/verification failed — {e}")
        sys.exit(1)

    # ── Test 2: Thread isolation ─────────────────────────────────────────
    thread_id_2 = f"test-thread-{uuid.uuid4().hex[:8]}"
    config_2 = {"configurable": {"thread_id": thread_id_2}}

    checkpoint_2 = {
        "v": 1,
        "id": str(uuid.uuid4()),
        "ts": "2025-01-01T00:01:00+00:00",
        "channel_values": {
            "messages": [
                {"type": "human", "content": "Different thread message"},
            ],
            "route": "simple",
            "model_used": "small-local",
        },
        "channel_versions": {},
        "versions_seen": {},
        "pending_sends": [],
    }

    try:
        await checkpointer.aput(config_2, checkpoint_2, {}, {})

        # Verify thread 1 still has its own data
        retrieved_1 = await checkpointer.aget_tuple(config_1)
        retrieved_2 = await checkpointer.aget_tuple(config_2)

        vals_1 = retrieved_1.checkpoint.get("channel_values", {})
        vals_2 = retrieved_2.checkpoint.get("channel_values", {})

        assert vals_1.get("route") == "complex-default", \
            f"Thread 1 route contaminated: {vals_1.get('route')}"
        assert vals_2.get("route") == "simple", \
            f"Thread 2 route wrong: {vals_2.get('route')}"
        assert vals_1.get("model_used") != vals_2.get("model_used"), \
            "Thread isolation failed: both threads have same model_used"

        print("OK: Thread isolation verified — threads have independent state.")
    except Exception as e:
        print(f"FAIL: Thread isolation test failed — {e}")
        sys.exit(1)

    print("\nAll standalone Redis checkpointer tests passed!")


if __name__ == "__main__":
    asyncio.run(main())
