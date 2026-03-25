"""Pure unit tests for web RAG chunking (no embedding model load)."""

from src.tools.web_retrieval import chunk_text


def test_chunk_text_splits_long_paragraph():
    para = "word " * 500
    chunks = chunk_text(para, max_chars=200, overlap=20)
    assert len(chunks) >= 2
    assert all(len(c) <= 250 for c in chunks)


def test_chunk_text_respects_paragraphs():
    text = "First block.\n\nSecond block here.\n\nThird."
    chunks = chunk_text(text, max_chars=100, overlap=10)
    assert len(chunks) >= 1
    assert "First" in chunks[0]
