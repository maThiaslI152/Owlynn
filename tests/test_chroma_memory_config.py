"""Mem0/Chroma memory configuration and legacy collection cleanup."""

from pathlib import Path

import pytest


def test_long_term_source_uses_lmstudio_nomic_embedder():
    root = Path(__file__).resolve().parents[1]
    text = (root / "src/memory/long_term.py").read_text(encoding="utf-8")
    assert '"model": "text-embedding-nomic-embed-text-v1.5@f16"' in text
    assert '"collection_name": "cowork_memory_nomic"' in text
    assert '"provider": "lmstudio"' in text
    # Legacy collection names should not be the active default
    assert '"collection_name": "cowork_memory"' not in text
    assert '"collection_name": "cowork_memory_mE5"' not in text


def test_legacy_cowork_memory_absent_when_chroma_reachable():
    try:
        import chromadb
        from src.config.settings import CHROMADB_HOST, CHROMADB_PORT

        client = chromadb.HttpClient(host=CHROMADB_HOST, port=CHROMADB_PORT)
    except Exception:
        pytest.skip("Chroma not reachable")
    names = {c.name for c in client.list_collections()}
    assert "cowork_memory" not in names
