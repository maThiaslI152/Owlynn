"""
Chunking + embedding rank for frontier-style web RAG (fetched pages and search snippets).
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any

import numpy as np

from src.config.settings import (
    WEB_RAG_CHUNK_CHARS,
    WEB_RAG_CHUNK_OVERLAP,
    WEB_RAG_EMBED_MODEL,
    WEB_RAG_ENABLED,
    WEB_RAG_MIN_CHARS_FOR_RANK,
    WEB_RAG_TOP_K,
    WEB_SEARCH_RERANK_TOP_N,
)

logger = logging.getLogger(__name__)

_embedder = None
_embed_lock = asyncio.Lock()


def _model_uses_e5_prefixes(model_name: str) -> bool:
    return "e5" in model_name.lower()


def chunk_text(text: str, max_chars: int, overlap: int) -> list[str]:
    """Split plain text into overlapping chunks by paragraph first, then by length."""
    text = (text or "").strip()
    if not text:
        return []

    parts = re.split(r"\n\s*\n+", text)
    chunks: list[str] = []
    buf = ""

    def flush_buf():
        nonlocal buf
        s = buf.strip()
        if s:
            chunks.append(s)
        buf = ""

    for p in parts:
        p = p.strip()
        if not p:
            continue
        if len(buf) + len(p) + 2 <= max_chars:
            buf = f"{buf}\n\n{p}" if buf else p
        else:
            if buf:
                flush_buf()
            if len(p) <= max_chars:
                buf = p
            else:
                start = 0
                while start < len(p):
                    end = min(start + max_chars, len(p))
                    piece = p[start:end].strip()
                    if piece:
                        chunks.append(piece)
                    start = end - overlap if end < len(p) else end
                buf = ""

    flush_buf()
    return chunks if chunks else ([text[:max_chars]] if text else [])


def _cosine_top_k(query_vec: np.ndarray, passage_vecs: np.ndarray, k: int) -> list[int]:
    q = query_vec.astype(np.float64)
    qn = np.linalg.norm(q)
    if qn < 1e-9:
        return list(range(min(k, passage_vecs.shape[0])))
    q = q / qn
    mat = passage_vecs.astype(np.float64)
    norms = np.linalg.norm(mat, axis=1, keepdims=True)
    norms = np.where(norms < 1e-9, 1.0, norms)
    mat = mat / norms
    sims = mat @ q
    order = np.argsort(-sims)
    return [int(i) for i in order[:k]]


async def _get_embedder():
    global _embedder
    async with _embed_lock:
        if _embedder is None:
            from sentence_transformers import SentenceTransformer

            logger.info("[web_rag] Loading embedding model: %s", WEB_RAG_EMBED_MODEL)

            def _load():
                return SentenceTransformer(WEB_RAG_EMBED_MODEL)

            _embedder = await asyncio.to_thread(_load)
    return _embedder


async def _encode_batch(model, texts: list[str], *, is_query: bool) -> np.ndarray:
    e5 = _model_uses_e5_prefixes(WEB_RAG_EMBED_MODEL)
    if e5:
        prefix = "query: " if is_query else "passage: "
        texts = [prefix + (t or "")[:8000] for t in texts]

    def _enc():
        return model.encode(texts, convert_to_numpy=True, show_progress_bar=False)

    return await asyncio.to_thread(_enc)


async def rank_chunks_to_source_pack(
    focus_query: str,
    page_url: str,
    plain_text: str,
    *,
    top_k: int | None = None,
) -> str | None:
    """
    Return a numbered "source pack" for the LLM, or None to signal caller should fall back.
    """
    if not WEB_RAG_ENABLED:
        return None
    fq = (focus_query or "").strip()
    if not fq:
        return None

    text = (plain_text or "").strip()
    if len(text) < WEB_RAG_MIN_CHARS_FOR_RANK:
        return None

    k = top_k if top_k is not None else WEB_RAG_TOP_K
    chunks = chunk_text(text, WEB_RAG_CHUNK_CHARS, WEB_RAG_CHUNK_OVERLAP)
    if not chunks:
        return None

    try:
        model = await _get_embedder()
        qv = await _encode_batch(model, [fq], is_query=True)
        pv = await _encode_batch(model, chunks, is_query=False)
        if pv.size == 0:
            return None
        idxs = _cosine_top_k(qv[0], pv, min(k, len(chunks)))
    except Exception as e:
        logger.warning("[web_rag] embedding rank failed: %s", e)
        return None

    lines = [
        f"Retrieved excerpts for: \"{fq}\"",
        f"Source URL: {page_url}",
        "Cite as [1], [2], ... matching the excerpts below.",
        "",
    ]
    for n, i in enumerate(idxs, start=1):
        excerpt = chunks[i].replace("\n", " ").strip()
        if len(excerpt) > 900:
            excerpt = excerpt[:897] + "..."
        lines.append(f"[{n}] {excerpt}")
        lines.append("")
    return "\n".join(lines).strip()


async def rerank_search_hits(
    focus_query: str,
    hits: list[dict[str, Any]],
    *,
    top_n: int | None = None,
) -> list[dict[str, Any]]:
    """
    Reorder search hit dicts (title, href, body keys) by embedding similarity to focus_query.
    On failure, returns the original list (possibly truncated).
    """
    if not WEB_RAG_ENABLED:
        return hits[: top_n or WEB_SEARCH_RERANK_TOP_N]
    fq = (focus_query or "").strip()
    if not fq or len(hits) <= 1:
        return hits[: top_n or WEB_SEARCH_RERANK_TOP_N]

    n_keep = top_n if top_n is not None else WEB_SEARCH_RERANK_TOP_N
    texts = []
    for h in hits:
        title = str(h.get("title") or h.get("name") or "")
        body = str(h.get("body") or h.get("snippet") or h.get("description") or "")
        texts.append(f"{title}\n{body}".strip()[:2000])

    try:
        model = await _get_embedder()
        qv = await _encode_batch(model, [fq], is_query=True)
        pv = await _encode_batch(model, texts, is_query=False)
        if pv.size == 0:
            return hits[:n_keep]
        idxs = _cosine_top_k(qv[0], pv, min(n_keep, len(hits)))
        return [hits[i] for i in idxs if 0 <= i < len(hits)]
    except Exception as e:
        logger.warning("[web_rag] search rerank failed: %s", e)
        return hits[:n_keep]
