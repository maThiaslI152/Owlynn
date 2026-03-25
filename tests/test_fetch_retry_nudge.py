"""Unit tests for post-tool fetch retry nudges (complex agent)."""

from langchain_core.messages import ToolMessage

from src.agent.nodes.complex import _fallback_for_blank_response, build_fetch_retry_nudge_messages


def _fetch_tool(content: str) -> ToolMessage:
    return ToolMessage(content=content, name="fetch_webpage", tool_call_id="tc1")


def test_nudge_when_no_extractable_text():
    m = _fetch_tool(
        "[fetch_webpage] No extractable text in static HTML (likely a JavaScript SPA"
    )
    out = build_fetch_retry_nudge_messages([m])
    assert len(out) == 1
    assert "fetch_webpage_dynamic" in out[0].content


def test_nudge_when_spa_metadata_note():
    m = _fetch_tool(
        "[Note: Page body is mostly empty in static HTML — typical of JavaScript apps."
    )
    out = build_fetch_retry_nudge_messages([m])
    assert len(out) == 1


def test_nudge_http_error_suggests_other_hit():
    m = _fetch_tool("[fetch_webpage] HTTP error 404 for https://example.com/x")
    out = build_fetch_retry_nudge_messages([m])
    assert len(out) == 1
    assert "web_search" in out[0].content


def test_dynamic_takes_precedence_over_http_when_both_in_batch():
    """Same batch: empty-body message wins over HTTP hint (elif branch)."""
    m1 = _fetch_tool("[fetch_webpage] HTTP error 500 for https://a")
    m2 = _fetch_tool("[fetch_webpage] No extractable text")
    out = build_fetch_retry_nudge_messages([m1, m2])
    assert len(out) == 1
    assert "fetch_webpage_dynamic" in out[0].content


def test_no_nudge_for_unrelated_tool():
    m = ToolMessage(content="x", name="web_search", tool_call_id="tc2")
    assert build_fetch_retry_nudge_messages([m]) == []


def test_no_nudge_for_substantial_fetch_body():
    body = "📄 Content from https://example.com:\n\n" + ("paragraph\n" * 50)
    m = _fetch_tool(body)
    assert build_fetch_retry_nudge_messages([m]) == []


def test_blank_response_fallback_when_web_search_failed():
    msg = ToolMessage(
        content="[web_search] Unable to retrieve online results for \"x\".",
        name="web_search",
        tool_call_id="tc3",
    )
    fb = _fallback_for_blank_response([msg], web_search_enabled=True)
    assert "couldn’t verify this online" in fb.content


def test_blank_response_fallback_generic_when_no_search_error_context():
    msg = _fetch_tool("📄 Content from https://example.com:\n\nGood content")
    fb = _fallback_for_blank_response([msg], web_search_enabled=True)
    assert "empty response" in fb.content


def test_blank_response_fallback_generic_no_web_first_turn_style():
    """No ToolMessages yet (e.g. first complex_llm call); still returns user-visible text."""
    fb = _fallback_for_blank_response([], web_search_enabled=False)
    assert "empty response" in fb.content
