"""Mem0/Qdrant memory configuration and legacy collection cleanup."""

from pathlib import Path

import pytest


def test_long_term_source_uses_lmstudio_nomic_embedder():
    root = Path(__file__).resolve().parents[1]
    text = (root / "src/memory/long_term.py").read_text(encoding="utf-8")
    assert '"model": "text-embedding-nomic-embed-text-v1.5@f16"' in text
    assert '"collection_name": "cowork_memory_nomic"' in text
    assert '"provider": "lmstudio"' in text
    assert '"provider": "qdrant"' in text
    assert '"port": 6333' in text
    assert '"embedding_model_dims": 768' in text
    # Legacy collection names should not be the active default
    assert '"collection_name": "cowork_memory"' not in text
    assert '"collection_name": "cowork_memory_mE5"' not in text


def test_legacy_cowork_memory_absent_when_qdrant_reachable():
    try:
        from qdrant_client import QdrantClient
        from src.config.settings import QDRANT_HOST, QDRANT_PORT

        client = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT)
        names = {c.name for c in client.get_collections().collections}
    except Exception:
        pytest.skip("Qdrant not reachable")
    assert "cowork_memory" not in names
