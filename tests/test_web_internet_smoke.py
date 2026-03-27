import re

import pytest

from src.tools import web_tools
from src.tools.web_tools import fetch_webpage, web_search


def _extract_urls(search_output: str) -> list[str]:
    return re.findall(r"^\s*URL:\s*(https?://\S+)\s*$", search_output, flags=re.MULTILINE)


def _skip_if_search_unavailable(out: str) -> None:
    if "[web_search] Error" in out or "[web_search] Unable to retrieve online results" in out:
        pytest.skip(f"Search providers unavailable in this environment: {out}")


@pytest.mark.asyncio
async def test_web_search_general_fallback_chain_mocked(monkeypatch):
    calls: list[str] = []

    async def brave_api(query: str, backend: str, news: bool, focus_query: str = ""):
        calls.append("brave_api")
        return None, web_tools.SearchAttempt("tier1", "brave_api", "empty")

    async def serper_api(query: str, backend: str, news: bool, focus_query: str = ""):
        calls.append("serper_api")
        return None, web_tools.SearchAttempt("tier1", "serper_api", "empty")

    async def tavily_api(query: str, backend: str, news: bool, focus_query: str = ""):
        calls.append("tavily_api")
        return None, web_tools.SearchAttempt("tier1", "tavily_api", "empty")

    async def curl_search(query: str, backend: str, news: bool, focus_query: str = ""):
        calls.append("curl_cffi")
        return None, web_tools.SearchAttempt("tier1", "curl_cffi", "empty")

    async def wttr(query: str, backend: str, news: bool):
        calls.append("wttr")
        return None

    async def ddg_http(query: str, backend: str, news: bool, focus_query: str = ""):
        calls.append("ddg_http")
        return None

    async def bing(query: str, backend: str, news: bool, focus_query: str = ""):
        calls.append("bing")
        return (
            '🔍 Web search results for: "python programming language" (Backend: auto, via Bing (HTTP))\n\n'
            "**1. Python**\n"
            "   URL: https://www.python.org/\n"
            "   Python language homepage\n"
        )

    monkeypatch.setattr(web_tools, "_web_search_wttr_in", wttr)
    monkeypatch.setattr(web_tools, "_web_search_api_brave", brave_api)
    monkeypatch.setattr(web_tools, "_web_search_api_serper", serper_api)
    monkeypatch.setattr(web_tools, "_web_search_api_tavily", tavily_api)
    monkeypatch.setattr(web_tools, "_web_search_curl_cffi", curl_search)
    monkeypatch.setattr(web_tools, "_web_search_httpx_ddg_html", ddg_http)
    monkeypatch.setattr(web_tools, "_web_search_bing_httpx", bing)
    monkeypatch.setattr(web_tools, "_candidate_providers", lambda backend: ["brave", "serper", "tavily"])
    monkeypatch.setattr(web_tools, "_get_ddgs_class", lambda: None)

    out = await web_search.ainvoke({"query": "python programming language", "backend": "auto"})
    assert calls == [
        "wttr",
        "brave_api",
        "serper_api",
        "tavily_api",
        "curl_cffi",
        "ddg_http",
        "bing",
    ]
    assert "search results for" in out
    assert "URL: https://www.python.org/" in out


@pytest.mark.asyncio
async def test_web_search_news_flow_mocked(monkeypatch):
    calls: list[str] = []

    async def wttr(query: str, backend: str, news: bool):
        calls.append("wttr")
        return "unexpected"

    async def brave_api(query: str, backend: str, news: bool, focus_query: str = ""):
        calls.append("brave_api")
        return None, web_tools.SearchAttempt("tier1", "brave_api", "empty")

    async def serper_api(query: str, backend: str, news: bool, focus_query: str = ""):
        calls.append("serper_api")
        return None, web_tools.SearchAttempt("tier1", "serper_api", "empty")

    async def tavily_api(query: str, backend: str, news: bool, focus_query: str = ""):
        calls.append("tavily_api")
        return None, web_tools.SearchAttempt("tier1", "tavily_api", "empty")

    async def curl_search(query: str, backend: str, news: bool, focus_query: str = ""):
        calls.append("curl_cffi")
        return None, web_tools.SearchAttempt("tier1", "curl_cffi", "empty")

    async def ddg_http(query: str, backend: str, news: bool, focus_query: str = ""):
        calls.append("ddg_http")
        return None

    async def bing(query: str, backend: str, news: bool, focus_query: str = ""):
        calls.append("bing")
        return None

    async def ddg_lite(query: str, backend: str, news: bool, focus_query: str = ""):
        calls.append("ddg_lite")
        return (
            '🔍 News search results for: "latest game industry news" (Backend: auto, via DDG Lite (HTTP))\n\n'
            "**1. Game Industry News**\n"
            "   URL: https://example.com/news\n"
            "   Latest updates\n"
        )

    monkeypatch.setattr(web_tools, "_web_search_wttr_in", wttr)
    monkeypatch.setattr(web_tools, "_web_search_api_brave", brave_api)
    monkeypatch.setattr(web_tools, "_web_search_api_serper", serper_api)
    monkeypatch.setattr(web_tools, "_web_search_api_tavily", tavily_api)
    monkeypatch.setattr(web_tools, "_web_search_curl_cffi", curl_search)
    monkeypatch.setattr(web_tools, "_web_search_httpx_ddg_html", ddg_http)
    monkeypatch.setattr(web_tools, "_web_search_bing_httpx", bing)
    monkeypatch.setattr(web_tools, "_web_search_ddg_lite_httpx", ddg_lite)
    monkeypatch.setattr(web_tools, "_candidate_providers", lambda backend: ["brave", "serper", "tavily"])
    monkeypatch.setattr(web_tools, "_get_ddgs_class", lambda: None)

    out = await web_search.ainvoke(
        {"query": "latest game industry news", "backend": "auto", "news": True}
    )
    # wttr fast-path is bypassed for news=True
    assert calls == [
        "brave_api",
        "serper_api",
        "tavily_api",
        "curl_cffi",
        "ddg_http",
        "bing",
        "ddg_lite",
    ]
    assert "News search results" in out
    assert "URL: https://example.com/news" in out


@pytest.mark.network
@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("label", "query", "kwargs"),
    [
        ("general", "python programming language", {"backend": "auto"}),
        ("news", "AI model release news 2026", {"backend": "auto", "news": True}),
        ("games", "latest game industry news", {"backend": "auto", "news": True}),
        ("weather", "what the weather like in bangkok", {"backend": "auto"}),
        ("other", "what is photosynthesis", {"backend": "auto"}),
    ],
)
async def test_web_search_common_internet_scenarios(label: str, query: str, kwargs: dict):
    out = await web_search.ainvoke({"query": query, **kwargs})
    # Weather has an independent wttr path and should not silently fail.
    if label == "weather":
        assert "[web_search] Error" not in out
    else:
        _skip_if_search_unavailable(out)

    # Weather can return either wttr weather card or normal search results.
    if label == "weather":
        if "Weather for" in out and "Temperature:" in out:
            return
        assert "search results for" in out
        assert "URL:" in out
        return

    assert "search results for" in out
    assert "URL:" in out


@pytest.mark.network
@pytest.mark.asyncio
async def test_web_search_outputs_direct_urls_not_ddg_redirect_wrappers():
    out = await web_search.ainvoke(
        {"query": "open source llm news", "backend": "auto", "news": True}
    )
    _skip_if_search_unavailable(out)
    urls = _extract_urls(out)
    assert urls, "Expected at least one URL in search output"
    assert all("/l/?uddg=" not in u for u in urls)


@pytest.mark.network
@pytest.mark.asyncio
async def test_search_then_fetch_returns_non_empty_text_or_actionable_message():
    search = await web_search.ainvoke(
        {
            "query": "python programming wikipedia",
            "backend": "auto",
            "focus_query": "What is Python programming language?",
        }
    )
    _skip_if_search_unavailable(search)
    urls = _extract_urls(search)
    assert urls, "Expected at least one URL from web_search"

    url = urls[0]
    fetched = await fetch_webpage.ainvoke(
        {"url": url, "focus_query": "What is Python programming language?"}
    )

    # Ensure we never regress to a blank content response.
    assert fetched != f"📄 Content from {url}:\n\n"
    assert fetched.strip()
    assert (
        fetched.startswith("📄")
        or fetched.startswith("[fetch_webpage]")
        or fetched.startswith("[fetch_webpage_dynamic]")
    )
