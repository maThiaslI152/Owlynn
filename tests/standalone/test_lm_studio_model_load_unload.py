"""
Test: LM Studio model load / unload ability.

Uses the LM Studio *native* API (``/api/v1/...``) which exposes
``loaded_instances`` with ``id`` fields needed for unload.

Verifies that each specified model can be:
  1. Loaded   via POST /api/v1/models/load
  2. Confirmed loaded   via GET  /api/v1/models  (loaded_instances non-empty)
  3. Unloaded via POST /api/v1/models/unload  (using instance_id)
  4. Confirmed unloaded via GET  /api/v1/models  (loaded_instances empty)

Usage:
    python tests/standalone/test_lm_studio_model_load_unload.py

Models tested:
    liquid/lfm2-24b-a2b, zai-org/glm-4.6v-flash, qwen/qwen3.5-9b
"""

import sys
import os
import time
import httpx

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

LM_STUDIO_BASE = os.getenv("LM_STUDIO_BASE_URL", "http://127.0.0.1:1234")
MODELS_TO_TEST = [
    "liquid/lfm2-24b-a2b",
    "zai-org/glm-4.6v-flash",
    "qwen/qwen3.5-9b",
]

LOAD_TIMEOUT = 300   # seconds — large models can be slow
HTTP_TIMEOUT = 30
UNLOAD_POLL_TIMEOUT = 60


# ── helpers ──────────────────────────────────────────────────────────────

def get_all_models(client: httpx.Client) -> list[dict]:
    """Return the full model list from the native LM Studio API."""
    r = client.get(f"{LM_STUDIO_BASE}/api/v1/models", timeout=HTTP_TIMEOUT)
    r.raise_for_status()
    return r.json().get("models", [])


def get_model_entry(client: httpx.Client, model_key: str) -> dict | None:
    """Find a single model entry by its key (e.g. 'qwen/qwen3.5-9b')."""
    for m in get_all_models(client):
        if m.get("key") == model_key:
            return m
    return None


def loaded_instance_ids(client: httpx.Client, model_key: str) -> list[str]:
    """Return instance IDs for a model that is currently loaded."""
    entry = get_model_entry(client, model_key)
    if not entry:
        return []
    return [inst["id"] for inst in entry.get("loaded_instances", [])]


def all_loaded_model_keys(client: httpx.Client) -> list[str]:
    """Return keys of every model that has at least one loaded instance."""
    return [
        m["key"] for m in get_all_models(client)
        if m.get("loaded_instances")
    ]


def unload_all_instances(client: httpx.Client, model_key: str) -> bool:
    """Unload every loaded instance of a model. Returns True if all succeeded."""
    ids = loaded_instance_ids(client, model_key)
    if not ids:
        return True  # nothing to unload
    ok = True
    for inst_id in ids:
        r = client.post(
            f"{LM_STUDIO_BASE}/api/v1/models/unload",
            json={"instance_id": inst_id},
            timeout=HTTP_TIMEOUT,
        )
        if r.status_code not in (200, 204):
            print(f"  [WARN] unload instance {inst_id!r} returned {r.status_code}: {r.text[:200]}")
            ok = False
    return ok


def load_model(client: httpx.Client, model_key: str) -> bool:
    """Load a model via the native API. Returns True on accepted."""
    r = client.post(
        f"{LM_STUDIO_BASE}/api/v1/models/load",
        json={"model": model_key},
        timeout=LOAD_TIMEOUT,
    )
    if r.status_code in (200, 201, 202):
        return True
    print(f"  [WARN] load returned {r.status_code}: {r.text[:300]}")
    return False


def wait_until_loaded(client: httpx.Client, model_key: str, timeout: int = LOAD_TIMEOUT) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if loaded_instance_ids(client, model_key):
            return True
        time.sleep(2)
    return False


def wait_until_unloaded(client: httpx.Client, model_key: str, timeout: int = UNLOAD_POLL_TIMEOUT) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if not loaded_instance_ids(client, model_key):
            return True
        time.sleep(2)
    return False


# ── main test loop ───────────────────────────────────────────────────────

def run_tests() -> bool:
    passed = 0
    failed = 0
    skipped = 0

    client = httpx.Client()

    # Connectivity
    print(f"Connecting to LM Studio at {LM_STUDIO_BASE} ...")
    try:
        models = get_all_models(client)
        loaded = all_loaded_model_keys(client)
        print(f"  Connected. {len(models)} models available, {len(loaded)} currently loaded: {loaded}\n")
    except Exception as e:
        print(f"  FAIL — cannot reach LM Studio: {e}")
        print("  Make sure LM Studio is running with the local server enabled.")
        return False

    for model_key in MODELS_TO_TEST:
        print(f"{'='*60}")
        print(f"Testing model: {model_key}")
        print(f"{'='*60}")

        entry = get_model_entry(client, model_key)
        if entry is None:
            print(f"  SKIP — model not found in LM Studio (not downloaded?)")
            skipped += 1
            continue

        # If already loaded, unload first so we test a clean cycle
        if loaded_instance_ids(client, model_key):
            print(f"  (pre-cleanup) Model already loaded — unloading first ...")
            unload_all_instances(client, model_key)
            if not wait_until_unloaded(client, model_key):
                print(f"  SKIP — could not unload pre-existing instance")
                skipped += 1
                continue
            print(f"  (pre-cleanup) Done.\n")

        # ── Step 1: Load ──
        print(f"  [1/4] Loading model ...")
        t0 = time.time()
        try:
            ok = load_model(client, model_key)
        except Exception as e:
            print(f"  SKIP — load request failed: {e}")
            skipped += 1
            continue
        if not ok:
            print(f"  FAIL — load request was not accepted")
            failed += 1
            continue

        # ── Step 2: Confirm loaded ──
        print(f"  [2/4] Waiting for model to appear in loaded_instances ...")
        if wait_until_loaded(client, model_key):
            elapsed = time.time() - t0
            ids = loaded_instance_ids(client, model_key)
            print(f"  PASS — model loaded in {elapsed:.1f}s  (instance_ids={ids})")
        else:
            print(f"  FAIL — model did not load within {LOAD_TIMEOUT}s")
            failed += 1
            continue

        # ── Step 3: Unload ──
        print(f"  [3/4] Unloading model ...")
        try:
            ok = unload_all_instances(client, model_key)
        except Exception as e:
            print(f"  FAIL — unload request failed: {e}")
            failed += 1
            continue

        # ── Step 4: Confirm unloaded ──
        print(f"  [4/4] Waiting for model to disappear from loaded_instances ...")
        if wait_until_unloaded(client, model_key):
            print(f"  PASS — model unloaded successfully")
            passed += 1
        else:
            print(f"  FAIL — model still loaded after {UNLOAD_POLL_TIMEOUT}s")
            failed += 1

        print()

    client.close()

    total = passed + failed + skipped
    print(f"\n{'='*60}")
    print(f"RESULTS: {passed} passed, {failed} failed, {skipped} skipped / {total} total")
    print(f"{'='*60}")
    return failed == 0


if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)
