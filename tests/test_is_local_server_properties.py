"""
Property-based tests for is_local_server classification.

# Feature: deepseek-hybrid-integration, Property 6: is_local_server Classification
# Validates: Requirements 9.1, 9.3
"""

from hypothesis import given, settings
from hypothesis import strategies as st

from src.agent.lm_studio_compat import is_local_server

# ── Strategies ───────────────────────────────────────────────────────────

# URL-safe characters that are NOT "localhost" or "127.0.0.1" substrings
_safe_chars = st.sampled_from(
    list("abcdefghjkmnpqruvwxyz" "ABCDEFGHJKMNPQRUVWXYZ" "3456789" "-_/:.@")
)

# Short strings that cannot accidentally contain "localhost" or "127.0.0.1"
_safe_segment = st.text(_safe_chars, min_size=0, max_size=30).filter(
    lambda s: "localhost" not in s.lower() and "127.0.0.1" not in s
)

# Ports for local URLs
_port = st.integers(min_value=1, max_value=65535)


# ── Property 6: is_local_server Classification ──────────────────────────

class TestIsLocalServerProperty:
    """
    Property 6: For any URL string, is_local_server returns True iff the URL
    contains '127.0.0.1' or 'localhost'. All other URLs return False.
    """

    @given(port=_port, path=_safe_segment)
    @settings(max_examples=200)
    def test_localhost_urls_return_true(self, port, path):
        """URLs containing 'localhost' are classified as local."""
        url = f"http://localhost:{port}/{path}"
        assert is_local_server(url) is True

    @given(port=_port, path=_safe_segment)
    @settings(max_examples=200)
    def test_127_urls_return_true(self, port, path):
        """URLs containing '127.0.0.1' are classified as local."""
        url = f"http://127.0.0.1:{port}/{path}"
        assert is_local_server(url) is True

    @given(prefix=_safe_segment, suffix=_safe_segment)
    @settings(max_examples=200)
    def test_non_local_urls_return_false(self, prefix, suffix):
        """URLs without 'localhost' or '127.0.0.1' are classified as non-local."""
        url = f"https://api.{prefix}.com/{suffix}"
        assert is_local_server(url) is False

    @given(data=st.data())
    @settings(max_examples=200)
    def test_cloud_endpoints_return_false(self, data):
        """Known cloud API endpoints are never classified as local."""
        endpoint = data.draw(st.sampled_from([
            "https://api.deepseek.com/v1",
            "https://api.openai.com/v1",
            "https://api.anthropic.com/v1",
            "https://generativelanguage.googleapis.com/v1",
            "https://models.inference.ai.azure.com",
        ]))
        assert is_local_server(endpoint) is False

    @given(url=st.text(min_size=0, max_size=100))
    @settings(max_examples=300)
    def test_iff_contains_local_marker(self, url):
        """is_local_server returns True iff '127.0.0.1' or 'localhost' is in the URL."""
        expected = "127.0.0.1" in url or "localhost" in url
        assert is_local_server(url) is expected
