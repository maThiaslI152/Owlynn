"""
Enhanced Web Search — Adds SearXNG (self-hosted metasearch) and improved extraction.

SearXNG is the recommended search backend for local setups:
- No API keys needed
- No bot blocking / CAPTCHAs
- Aggregates Google, Bing, DuckDuckGo, Wikipedia, etc.
- Easy to self-host via Docker

Also adds a smarter content extraction pipeline for fetch_webpage.
"""

import asyncio
import json
import logging
from urllib.parse import quote_plus

from src.config.settings import SEARXNG_URL

logger = logging.getLogger(__name__)


async def searxng_search(
    query: str,
    categories: str = "general",
    max_results: int = 8,
) -> list[dict] | None:
    """
    Search via a local SearXNG instance. Returns list of hit dicts or None on failure.
    """
    if not SEARXNG_URL:
        return None

    import httpx

    params = {
        "q": query,
        "format": "json",
        "categories": categories,
        "language": "en",
        "safesearch": 0,
    }
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(f"{SEARXNG_URL}/search", params=params)
            resp.raise_for_status()
            data = resp.json()
    except Exception as e:
        logger.warning("SearXNG search failed: %s", e)
        return None

    results = data.get("results", [])
    if not results:
        return None

    hits = []
    for r in results[:max_results]:
        hits.append({
            "title": r.get("title", "No title"),
            "href": r.get("url", ""),
            "body": r.get("content", r.get("snippet", "No snippet")),
            "engine": r.get("engine", "unknown"),
        })
    return hits if hits else None


async def searxng_available() -> bool:
    """Check if SearXNG is reachable."""
    if not SEARXNG_URL:
        return False
    import httpx
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{SEARXNG_URL}/healthz")
            return resp.status_code == 200
    except Exception:
        return False
