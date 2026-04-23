"""
Bug condition exploration tests for the router tool awareness fix.

These tests demonstrate the bug exists in the UNFIXED code:
- _looks_like_prose_tool_stall does not accept workspace_files_present parameter
- Long prose responses (>=420 chars) are NOT detected as stalls even when workspace files are present
- Tool guidance lacks explicit read_workspace_file and create_pdf instructions

# Feature: router-tool-awareness-fix
# Property 1: Bug Condition — Prose Stall Detection Misses Long Responses With Workspace Files
"""

import sys
from unittest.mock import MagicMock

# Must mock mem0 before importing src modules
sys.modules["mem0"] = MagicMock()

import pytest
from langchain_core.messages import AIMessage

from src.agent.nodes.complex import _looks_like_prose_tool_stall, COMPLEX_TOOL_GUIDANCE_WEB


# ── Test 1: Bug condition — long prose with workspace files should be detected as stall ──

def test_long_prose_with_workspace_files_detected_as_stall():
    """
    **Validates: Requirements 1.1, 2.1**

    The FIXED version should accept workspace_files_present=True and return True
    for long prose responses when workspace files are present.
    On UNFIXED code, this raises TypeError because the parameter doesn't exist.
    """
    long_prose = (
        "What specific aspects would you like me to summarize from this file? "
        "I can help with various types of analysis including data exploration, "
        "statistical summaries, trend identification, and more. Please let me "
        "know what kind of summary you're looking for and I'll be happy to help "
        "you with that. I can also create visualizations or charts if that would "
        "be useful for understanding the data better. Just let me know your "
        "preferences and I'll get started right away on the analysis. "
        "There are many different approaches we could take depending on your needs."
    )
    assert len(long_prose) >= 500, f"Test prose must be >= 500 chars, got {len(long_prose)}"

    response = AIMessage(content=long_prose)
    # This call will raise TypeError on unfixed code (no workspace_files_present param)
    result = _looks_like_prose_tool_stall(response, workspace_files_present=True)
    assert result is True


# ── Test 2: Bug condition — long prose returns False on current code ──

def test_long_prose_returns_false_on_current_code():
    """
    **Validates: Requirements 1.1**

    Demonstrates the bug: a 500+ char prose response with no tool_calls
    is NOT detected as a stall by the current code (returns False because
    len >= 420). This PASSES on unfixed code, proving the bug exists.
    """
    long_prose = (
        "What specific aspects would you like me to summarize from this file? "
        "I can help with various types of analysis including data exploration, "
        "statistical summaries, trend identification, and more. Please let me "
        "know what kind of summary you're looking for and I'll be happy to help "
        "you with that. I can also create visualizations or charts if that would "
        "be useful for understanding the data better. Just let me know your "
        "preferences and I'll get started right away on the analysis. "
        "There are many different approaches we could take depending on your needs."
    )
    assert len(long_prose) >= 500, f"Test prose must be >= 500 chars, got {len(long_prose)}"

    response = AIMessage(content=long_prose)
    result = _looks_like_prose_tool_stall(response)
    # On unfixed code, this returns False — the bug: long prose is NOT detected as stall
    assert result is False


# ── Test 3: Tool guidance gap — no explicit read_workspace_file instruction ──

def test_tool_guidance_missing_explicit_read_workspace_file_instruction():
    """
    **Validates: Requirements 1.4, 1.5**

    After the fix: COMPLEX_TOOL_GUIDANCE_WEB MUST contain an explicit
    instruction to call read_workspace_file when workspace files are mentioned.
    """
    assert "MUST call read_workspace_file" in COMPLEX_TOOL_GUIDANCE_WEB


# ── Test 4: Tool guidance gap — no explicit create_pdf instruction ──

def test_tool_guidance_missing_explicit_create_pdf_instruction():
    """
    **Validates: Requirements 1.4, 1.5**

    After the fix: COMPLEX_TOOL_GUIDANCE_WEB MUST contain an explicit
    instruction to use the create_pdf tool for PDF requests.
    """
    assert "use the `create_pdf` tool" in COMPLEX_TOOL_GUIDANCE_WEB


# ══════════════════════════════════════════════════════════════════════════════
# Property 2: Preservation — Non-File Prose and Tool-Call Response Behavior
#
# These tests capture the CURRENT (unfixed) behavior of _looks_like_prose_tool_stall
# using the single-argument signature.  They MUST PASS on unfixed code to establish
# the baseline that the fix must preserve.
#
# **Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.5**
# ══════════════════════════════════════════════════════════════════════════════


# ── Test 5: Preservation — tool-call responses always return False ──

def test_tool_call_responses_return_false():
    """
    **Validates: Requirements 3.1**

    Any AIMessage that carries tool_calls must NOT be flagged as a prose stall,
    regardless of content length.  This is the most important preservation
    guarantee: real tool-calling responses must pass through untouched.
    """
    # Short content with tool_calls
    short_with_tools = AIMessage(
        content="Let me read that file for you.",
        tool_calls=[{"name": "read_workspace_file", "args": {"filename": "grades.csv"}, "id": "tc1"}],
    )
    assert _looks_like_prose_tool_stall(short_with_tools) is False

    # Long content with tool_calls
    long_content = "I will analyze the data. " * 30  # well over 420 chars
    long_with_tools = AIMessage(
        content=long_content,
        tool_calls=[{"name": "web_search", "args": {"query": "test"}, "id": "tc2"}],
    )
    assert _looks_like_prose_tool_stall(long_with_tools) is False


# ── Test 6: Preservation — short prose (<420 chars) returns True ──

def test_short_prose_returns_true():
    """
    **Validates: Requirements 3.3**

    A short prose response (< 420 chars) with no tool_calls is detected as a
    stall by the existing heuristic.  This must remain true after the fix.
    """
    short_prose = "I can help you with that. What would you like to know?"
    assert len(short_prose) < 420

    response = AIMessage(content=short_prose)
    assert _looks_like_prose_tool_stall(response) is True


# ── Test 7: Preservation — long prose (>=420 chars) without files returns False ──

def test_long_prose_without_files_returns_false():
    """
    **Validates: Requirements 3.2**

    A long prose response (>= 420 chars) with no tool_calls and no workspace
    file context returns False under the current heuristic.  When the fix adds
    the workspace_files_present parameter, calling with the default (False)
    must preserve this behavior.
    """
    long_prose = (
        "Let me explain the various approaches we could take for this analysis. "
        "First, we could look at the overall distribution of values across all "
        "columns to identify any outliers or unusual patterns. Second, we could "
        "compute summary statistics such as mean, median, standard deviation, "
        "and quartiles for each numeric column. Third, we could examine "
        "correlations between different variables to find relationships. Fourth, "
        "we could create visualizations to make the patterns more apparent. "
        "Finally, we could run some basic statistical tests to validate any "
        "hypotheses about the data. Which approach interests you most?"
    )
    assert len(long_prose) >= 420, f"Test prose must be >= 420 chars, got {len(long_prose)}"

    response = AIMessage(content=long_prose)
    assert _looks_like_prose_tool_stall(response) is False


# ── Test 8: Preservation — response mentioning read_workspace_file returns True ──

def test_response_mentioning_read_workspace_file_returns_true():
    """
    **Validates: Requirements 3.5**

    The existing keyword detection returns True when the response text contains
    "read_workspace_file", regardless of length.  This preserves the heuristic
    that catches local models that *talk about* the tool instead of calling it.
    """
    prose_with_keyword = (
        "I see you have uploaded a file. I should use read_workspace_file to "
        "access its contents. Let me do that for you now so I can provide a "
        "proper analysis of the data contained within the uploaded document. "
        "This will allow me to give you accurate information rather than "
        "guessing about what the file contains. The read_workspace_file tool "
        "is the right approach here for accessing workspace attachments. "
        "I will proceed to read the file contents and provide a thorough summary."
    )

    response = AIMessage(content=prose_with_keyword)
    assert _looks_like_prose_tool_stall(response) is True


# ── Test 9: Preservation — empty response returns True ──

def test_empty_response_returns_true():
    """
    **Validates: Requirements 3.3**

    An empty AIMessage (no content, no tool_calls) is treated as a stall.
    This must remain true after the fix.
    """
    response = AIMessage(content="")
    assert _looks_like_prose_tool_stall(response) is True
