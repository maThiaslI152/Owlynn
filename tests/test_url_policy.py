"""SSRF URL policy for fetch_webpage."""

import pytest

from src.tools.url_policy import url_fetch_blocked_reason
from src.tools.web_tools import fetch_webpage


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost/path",
        "https://127.0.0.1/",
        "http://0.0.0.0/",
        "https://[::1]/",
        "ftp://example.com/",
        "not-a-url",
        "",
        "file:///etc/passwd",
    ],
)
def test_url_fetch_blocked_for_unsafe_or_invalid(url: str):
    assert url_fetch_blocked_reason(url) is not None


def test_blocks_private_ip_literal_hostname():
    assert url_fetch_blocked_reason("http://192.168.1.1/") is not None
    assert url_fetch_blocked_reason("http://10.0.0.1/") is not None


@pytest.mark.network
def test_public_https_example_allowed():
    assert url_fetch_blocked_reason("https://example.com/") is None


@pytest.mark.asyncio
async def test_fetch_webpage_tool_blocks_loopback():
    r = await fetch_webpage.ainvoke({"url": "http://127.0.0.1/nope"})
    assert "Blocked" in r
