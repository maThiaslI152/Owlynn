import pytest
from src.tools.web_tools import (
    _candidate_providers,
    _structured_search_failure,
    SearchAttempt,
    detect_bot_block,
    fetch_webpage,
    fetch_webpage_dynamic,
    unwrap_redirect_search_url,
    web_search,
    _html_static_fallback_text,
)


def test_unwrap_ddg_redirect_url():
    u = "https://duckduckgo.com/l/?uddg=https%3A%2F%2Ftheaitrack.com%2Fa&rut=abc"
    assert unwrap_redirect_search_url(u) == "https://theaitrack.com/a"
    assert unwrap_redirect_search_url("https://example.com/x") == "https://example.com/x"


def test_html_static_fallback_text():
    html = (
        "<html><head><title>My Title</title>"
        '<meta name="description" content="Hello world"/>'
        '</head><body><div id="root"></div></body></html>'
    )
    fb = _html_static_fallback_text(html)
    assert "My Title" in fb
    assert "Hello world" in fb


def test_detect_bot_block_markers():
    html = "<html><body>One last step <script src='https://challenges.cloudflare.com'></script></body></html>"
    assert detect_bot_block(html) is True
    assert detect_bot_block("<html><body>Normal content</body></html>") is False


def test_candidate_providers_backend_override():
    assert _candidate_providers("brave") == ["brave"]
    assert _candidate_providers("serper") == ["serper"]
    assert _candidate_providers("tavily") == ["tavily"]


def test_structured_search_failure_format():
    out = _structured_search_failure(
        "deepseek r2",
        [
            SearchAttempt("tier1", "brave_api", "unavailable_key", "missing key"),
            SearchAttempt("tier1", "curl_cffi", "blocked_by_captcha", "Cloudflare Turnstile challenge detected"),
        ],
    )
    assert "[web_search] Unable to retrieve online results" in out
    assert "tier1 / brave_api" in out
    assert "tier1 / curl_cffi" in out


@pytest.mark.network
@pytest.mark.asyncio
async def test_web_search():
    # Invoke using tool.ainvoke
    results = await web_search.ainvoke({"query": "python programming", "backend": "auto"})
    assert "🔍" in results
    assert "URL:" in results

@pytest.mark.network
@pytest.mark.asyncio
async def test_web_search_google():
    results = await web_search.ainvoke({"query": "python programming", "backend": "google"})
    assert "🔍" in results
    assert "Backend: google" in results

@pytest.mark.network
@pytest.mark.asyncio
async def test_fetch_webpage():
    results = await fetch_webpage.ainvoke({"url": "https://example.com"})
    assert "📄 Content from" in results
    assert "Example Domain" in results

@pytest.mark.network
@pytest.mark.asyncio
async def test_fetch_webpage_dynamic():
    results = await fetch_webpage_dynamic.ainvoke({"url": "https://example.com"})
    assert "📄 [Dynamic] Content from" in results
    assert "Example Domain" in results
