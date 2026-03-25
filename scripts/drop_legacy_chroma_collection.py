#!/usr/bin/env python3
"""
Remove the legacy Chroma collection `cowork_memory` (BGE embedder).
Safe to run when Chroma is up; no-op if the collection is missing or DB is down.
"""
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.config.settings import CHROMADB_HOST, CHROMADB_PORT

LEGACY_COLLECTION = "cowork_memory"


def main() -> int:
    try:
        import chromadb
    except ImportError:
        print("chromadb is not installed; skip.", file=sys.stderr)
        return 0

    try:
        client = chromadb.HttpClient(host=CHROMADB_HOST, port=CHROMADB_PORT)
    except Exception as e:
        print(f"Chroma not reachable at {CHROMADB_HOST}:{CHROMADB_PORT} ({e}); skip.", file=sys.stderr)
        return 0

    names = {c.name for c in client.list_collections()}
    if LEGACY_COLLECTION not in names:
        print(f"No collection {LEGACY_COLLECTION!r}; nothing to remove.")
        return 0

    client.delete_collection(name=LEGACY_COLLECTION)
    print(f"Deleted Chroma collection {LEGACY_COLLECTION!r}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
