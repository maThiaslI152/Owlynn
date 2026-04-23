#!/usr/bin/env python3
"""
Remove the legacy Mem0 collection `cowork_memory` (BGE embedder) from Qdrant.
Safe to run when Qdrant is up; no-op if the collection is missing or DB is down.
"""
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.config.settings import QDRANT_HOST, QDRANT_PORT

LEGACY_COLLECTION = "cowork_memory"


def main() -> int:
    try:
        from qdrant_client import QdrantClient
    except ImportError:
        print("qdrant-client is not installed; skip.", file=sys.stderr)
        return 0

    try:
        client = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT)
        collections = client.get_collections().collections
    except Exception as e:
        print(f"Qdrant not reachable at {QDRANT_HOST}:{QDRANT_PORT} ({e}); skip.", file=sys.stderr)
        return 0

    names = {c.name for c in collections}
    if LEGACY_COLLECTION not in names:
        print(f"No collection {LEGACY_COLLECTION!r}; nothing to remove.")
        return 0

    client.delete_collection(collection_name=LEGACY_COLLECTION)
    print(f"Deleted Qdrant collection {LEGACY_COLLECTION!r}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
