import pytest
from src.tools.web_tools import web_search, fetch_webpage, fetch_webpage_dynamic

@pytest.mark.asyncio
async def test_web_search():
    # Invoke using tool.ainvoke
    results = await web_search.ainvoke({"query": "python programming", "backend": "auto"})
    assert "🔍" in results
    assert "URL:" in results

@pytest.mark.asyncio
async def test_web_search_google():
    results = await web_search.ainvoke({"query": "python programming", "backend": "google"})
    assert "🔍" in results
    assert "Backend: google" in results

@pytest.mark.asyncio
async def test_fetch_webpage():
    results = await fetch_webpage.ainvoke({"url": "https://example.com"})
    assert "📄 Content from" in results
    assert "Example Domain" in results

@pytest.mark.asyncio
async def test_fetch_webpage_dynamic():
    results = await fetch_webpage_dynamic.ainvoke({"url": "https://example.com"})
    assert "📄 [Dynamic] Content from" in results
    assert "Example Domain" in results
