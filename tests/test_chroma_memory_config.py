"""Mem0/Chroma memory configuration and legacy collection cleanup."""

from pathlib import Path

import pytest


def test_long_term_source_uses_multilingual_e5_and_mE5_collection():
    root = Path(__file__).resolve().parents[1]
    text = (root / "src/memory/long_term.py").read_text(encoding="utf-8")
    assert '"model": "intfloat/multilingual-e5-small"' in text
    assert '"collection_name": "cowork_memory_mE5"' in text
    assert "cowork_memory_mE5" in text
    # Legacy collection name should not be the active default anymore
    assert '"collection_name": "cowork_memory"' not in text


def test_legacy_cowork_memory_absent_when_chroma_reachable():
    try:
        import chromadb
        from src.config.settings import CHROMADB_HOST, CHROMADB_PORT

        client = chromadb.HttpClient(host=CHROMADB_HOST, port=CHROMADB_PORT)
    except Exception:
        pytest.skip("Chroma not reachable")
    names = {c.name for c in client.list_collections()}
    assert "cowork_memory" not in names
