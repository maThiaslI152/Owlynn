"""
Property-based tests for the Cloud Fallback Anonymization Leak bugfix.

# Feature: cloud-fallback-anonymization-leak
# Property 1: Bug Condition — Fallback Models Receive Anonymized Input
#
# **Validates: Requirements 1.1, 1.2, 1.3, 1.4, 2.1, 2.2, 2.3, 2.4**
#
# When route is "complex-cloud", anonymization is enabled, and the cloud LLM
# call fails (rate limit 429, auth 401/403, generic error), the fallback local
# model should receive the ORIGINAL non-anonymized messages — not placeholder
# tokens like [NAME_1], [EMAIL_1], [PATH_1], [CUSTOM_1].
#
# On UNFIXED code these tests are EXPECTED TO FAIL, confirming the bug exists.
"""

import sys
from unittest.mock import MagicMock

sys.modules["mem0"] = MagicMock()

import asyncio
import re
import pytest
from unittest.mock import AsyncMock, patch
from hypothesis import given, settings, assume
from hypothesis import strategies as st
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from src.agent.state import AgentState


# ── Placeholder pattern that should NOT appear in fallback input ─────────

PLACEHOLDER_RE = re.compile(r"\[(NAME|EMAIL|PATH|CUSTOM|API_KEY|URL|IP|PHONE)_\d+\]")


# ── Known PII values used in tests ──────────────────────────────────────

KNOWN_NAME = "TestUser"
KNOWN_EMAIL = "testuser@example.com"
KNOWN_PATH = "/Users/testuser/project/main.py"
KNOWN_PII = [KNOWN_NAME, KNOWN_EMAIL, KNOWN_PATH]


# ── Strategies ───────────────────────────────────────────────────────────

# Generate random extra text to surround the PII
filler_text_st = st.text(
    min_size=0,
    max_size=80,
    alphabet=st.characters(whitelist_categories=("L", "N", "Z")),
)

# Error type strategy for the three fallback paths
error_type_st = st.sampled_from(["rate_limit_429", "auth_401", "generic_error"])


# ── Helpers ──────────────────────────────────────────────────────────────

def _build_pii_message(filler: str) -> str:
    """Build a message containing known PII values with optional filler text."""
    return (
        f"Hello {KNOWN_NAME}, {filler} email me at {KNOWN_EMAIL} "
        f"about {KNOWN_PATH}"
    )


def _make_state(text: str) -> dict:
    """Build a minimal AgentState dict for complex_llm_node on cloud route."""
    return {
        "messages": [HumanMessage(content=text)],
        "route": "complex-cloud",
        "mode": "tools_on",
        "web_search_enabled": True,
        "memory_context": "None",
        "persona": "Test persona",
        "response_style": None,
        "security_decision": None,
        "security_reason": None,
        "token_budget": 4096,
        "selected_toolboxes": ["all"],
    }


def _mock_profile() -> dict:
    """Profile with anonymization enabled and known PII context."""
    return {
        "name": KNOWN_NAME,
        "small_llm_base_url": "http://127.0.0.1:1234/v1",
        "cloud_llm_base_url": "https://api.deepseek.com/v1",
        "cloud_anonymization_enabled": True,
        "custom_sensitive_terms": [],
        "lm_studio_fold_system": True,
        "medium_models": {
            "default": "qwen/qwen3.5-9b",
            "vision": "zai-org/glm-4.6v-flash",
            "longctx": "LFM2 8B A1B GGUF Q8_0",
        },
    }


def _make_cloud_llm_that_raises(error_type: str):
    """
    Create a mock cloud LLM whose ainvoke raises the appropriate exception
    for the given error type. For rate_limit_429, both the initial call and
    the retry raise (to trigger the full fallback path).
    """
    mock_llm = MagicMock()
    mock_bound = MagicMock()

    if error_type == "rate_limit_429":
        exc = Exception("HTTP 429 Too Many Requests: rate limit exceeded")
    elif error_type == "auth_401":
        exc = Exception("HTTP 401 Unauthorized: invalid API key")
    else:
        exc = Exception("HTTP 500 Internal Server Error: something went wrong")

    mock_bound.ainvoke = AsyncMock(side_effect=exc)
    mock_bound.bind = MagicMock(return_value=mock_bound)
    mock_llm.bind_tools = MagicMock(return_value=mock_bound)
    mock_llm.bind = MagicMock(return_value=mock_bound)
    return mock_llm


def _make_capturing_fallback_llm():
    """
    Create a mock fallback LLM that captures the prompt_messages passed
    to its ainvoke call, so we can inspect what the fallback model received.
    """
    captured_prompts = []
    mock_llm = MagicMock()
    mock_response = AIMessage(content="Fallback response")
    mock_bound = MagicMock()

    async def _capture_ainvoke(messages):
        captured_prompts.append(messages)
        return mock_response

    mock_bound.ainvoke = AsyncMock(side_effect=_capture_ainvoke)
    mock_bound.bind = MagicMock(return_value=mock_bound)
    mock_llm.bind_tools = MagicMock(return_value=mock_bound)
    mock_llm.bind = MagicMock(return_value=mock_bound)
    return mock_llm, captured_prompts


def _extract_all_text_from_messages(messages: list) -> str:
    """Extract all text content from a list of LangChain messages."""
    parts = []
    for msg in messages:
        content = getattr(msg, "content", "")
        if isinstance(content, str):
            parts.append(content)
        elif isinstance(content, list):
            for block in content:
                if isinstance(block, str):
                    parts.append(block)
                elif isinstance(block, dict):
                    parts.append(str(block.get("text", "")))
        else:
            parts.append(str(content))
    return "\n".join(parts)


# ═════════════════════════════════════════════════════════════════════════
# Property 1: Bug Condition — Fallback Models Receive Anonymized Input
#
# **Validates: Requirements 1.1, 1.2, 1.3, 1.4, 2.1, 2.2, 2.3, 2.4**
#
# On UNFIXED code, these tests MUST FAIL — failure confirms the bug exists.
# The assertions encode the EXPECTED (correct) behavior: fallback models
# should receive original PII, not placeholder tokens.
# ═════════════════════════════════════════════════════════════════════════


class TestBugConditionFallbackAnonymizationLeak:
    """
    For any cloud route invocation where anonymization is enabled and the
    cloud LLM call fails, the fallback model SHALL receive the original
    non-anonymized messages with no [CATEGORY_N] placeholders.

    **Validates: Requirements 1.1, 1.2, 1.3, 1.4, 2.1, 2.2, 2.3, 2.4**
    """

    @given(filler=filler_text_st, error_type=error_type_st)
    @settings(max_examples=20, deadline=60000)
    @pytest.mark.asyncio
    async def test_fallback_receives_no_placeholders(
        self, filler: str, error_type: str
    ):
        """
        Property: For all cloud fallback scenarios with anonymization enabled,
        the prompt_messages passed to the fallback LLM must NOT contain any
        [CATEGORY_N] placeholder tokens.

        **Validates: Requirements 1.1, 1.2, 1.3, 2.1, 2.2, 2.3**
        """
        pii_text = _build_pii_message(filler)
        state = _make_state(pii_text)
        profile = _mock_profile()

        cloud_llm = _make_cloud_llm_that_raises(error_type)
        fallback_llm, captured_prompts = _make_capturing_fallback_llm()

        async def _get_cloud_llm():
            return cloud_llm

        async def _get_medium_llm(variant="default"):
            return fallback_llm

        with patch("src.agent.nodes.complex.get_cloud_llm", side_effect=_get_cloud_llm), \
             patch("src.agent.nodes.complex.get_medium_llm", side_effect=_get_medium_llm), \
             patch("src.agent.nodes.complex.get_profile", return_value=profile), \
             patch("src.agent.nodes.complex.asyncio.sleep", new_callable=AsyncMock):
            from src.agent.nodes.complex import complex_llm_node
            result = await complex_llm_node(state)

        # The fallback LLM must have been called
        assert len(captured_prompts) > 0, (
            f"Fallback LLM was never called for error_type={error_type!r}"
        )

        # Extract all text from the prompt messages sent to the fallback LLM
        fallback_text = _extract_all_text_from_messages(captured_prompts[0])

        # Assert NO placeholder tokens are present
        placeholders_found = PLACEHOLDER_RE.findall(fallback_text)
        assert len(placeholders_found) == 0, (
            f"Fallback LLM received placeholder tokens {placeholders_found} "
            f"for error_type={error_type!r}. "
            f"This confirms the bug: anonymized input leaked to fallback model."
        )

    @given(filler=filler_text_st, error_type=error_type_st)
    @settings(max_examples=20, deadline=60000)
    @pytest.mark.asyncio
    async def test_fallback_contains_original_pii(
        self, filler: str, error_type: str
    ):
        """
        Property: For all cloud fallback scenarios with anonymization enabled,
        the prompt_messages passed to the fallback LLM must contain the
        original PII values (name, email, path).

        **Validates: Requirements 2.1, 2.2, 2.3, 2.4**
        """
        pii_text = _build_pii_message(filler)
        state = _make_state(pii_text)
        profile = _mock_profile()

        cloud_llm = _make_cloud_llm_that_raises(error_type)
        fallback_llm, captured_prompts = _make_capturing_fallback_llm()

        async def _get_cloud_llm():
            return cloud_llm

        async def _get_medium_llm(variant="default"):
            return fallback_llm

        with patch("src.agent.nodes.complex.get_cloud_llm", side_effect=_get_cloud_llm), \
             patch("src.agent.nodes.complex.get_medium_llm", side_effect=_get_medium_llm), \
             patch("src.agent.nodes.complex.get_profile", return_value=profile), \
             patch("src.agent.nodes.complex.asyncio.sleep", new_callable=AsyncMock):
            from src.agent.nodes.complex import complex_llm_node
            result = await complex_llm_node(state)

        assert len(captured_prompts) > 0, (
            f"Fallback LLM was never called for error_type={error_type!r}"
        )

        fallback_text = _extract_all_text_from_messages(captured_prompts[0])

        # Assert original PII values ARE present in the fallback input
        for pii_value in KNOWN_PII:
            assert pii_value in fallback_text, (
                f"Fallback LLM input missing original PII value {pii_value!r} "
                f"for error_type={error_type!r}. "
                f"This confirms the bug: original content was replaced by placeholders."
            )


# ── Additional helpers for preservation tests ────────────────────────────

# Non-cloud route strategy
non_cloud_route_st = st.sampled_from(["complex-default", "complex-vision", "complex-longctx"])


def _make_state_with_route(text: str, route: str) -> dict:
    """Build a minimal AgentState dict for complex_llm_node with a given route."""
    return {
        "messages": [HumanMessage(content=text)],
        "route": route,
        "mode": "tools_on",
        "web_search_enabled": True,
        "memory_context": "None",
        "persona": "Test persona",
        "response_style": None,
        "security_decision": None,
        "security_reason": None,
        "token_budget": 4096,
        "selected_toolboxes": ["all"],
    }


def _mock_profile_anon_disabled() -> dict:
    """Profile with anonymization DISABLED."""
    return {
        "name": KNOWN_NAME,
        "small_llm_base_url": "http://127.0.0.1:1234/v1",
        "cloud_llm_base_url": "https://api.deepseek.com/v1",
        "cloud_anonymization_enabled": False,
        "custom_sensitive_terms": [],
        "lm_studio_fold_system": True,
        "medium_models": {
            "default": "qwen/qwen3.5-9b",
            "vision": "zai-org/glm-4.6v-flash",
            "longctx": "LFM2 8B A1B GGUF Q8_0",
        },
    }


def _make_capturing_cloud_llm(response_content: str = "Hello [NAME_1], your email is [EMAIL_1]"):
    """
    Create a mock cloud LLM that succeeds and captures the prompt_messages
    passed to its ainvoke call. Returns an AIMessage with the given content.
    """
    captured_prompts = []
    mock_llm = MagicMock()
    mock_response = AIMessage(content=response_content)
    mock_bound = MagicMock()

    async def _capture_ainvoke(messages):
        captured_prompts.append(messages)
        return mock_response

    mock_bound.ainvoke = AsyncMock(side_effect=_capture_ainvoke)
    mock_bound.bind = MagicMock(return_value=mock_bound)
    mock_llm.bind_tools = MagicMock(return_value=mock_bound)
    mock_llm.bind = MagicMock(return_value=mock_bound)
    return mock_llm, captured_prompts


def _make_capturing_cloud_llm_with_tool_calls(anon_mapping: dict):
    """
    Create a mock cloud LLM that succeeds and returns an AIMessage with
    tool_calls containing anonymized arguments. The tool call args use
    placeholders from the provided anon_mapping.

    Note: content is empty string so the deanonymization path for tool_calls
    is reached (when content is truthy, the code creates a new AIMessage
    losing tool_calls before the tool_call deanonymization branch).
    """
    captured_prompts = []
    mock_llm = MagicMock()

    # Build tool call args using placeholders
    tool_call_args = {"filename": "[PATH_1]", "query": "info about [NAME_1]"}
    mock_response = AIMessage(
        content="",
        tool_calls=[{
            "name": "read_workspace_file",
            "args": dict(tool_call_args),
            "id": "call_123",
        }],
    )

    mock_bound = MagicMock()

    async def _capture_ainvoke(messages):
        captured_prompts.append(messages)
        return mock_response

    mock_bound.ainvoke = AsyncMock(side_effect=_capture_ainvoke)
    mock_bound.bind = MagicMock(return_value=mock_bound)
    mock_llm.bind_tools = MagicMock(return_value=mock_bound)
    mock_llm.bind = MagicMock(return_value=mock_bound)
    return mock_llm, captured_prompts


def _make_capturing_local_llm():
    """
    Create a mock local LLM that captures the prompt_messages passed
    to its ainvoke call. Returns a simple AIMessage.
    """
    captured_prompts = []
    mock_llm = MagicMock()
    mock_response = AIMessage(content="Local model response")
    mock_bound = MagicMock()

    async def _capture_ainvoke(messages):
        captured_prompts.append(messages)
        return mock_response

    mock_bound.ainvoke = AsyncMock(side_effect=_capture_ainvoke)
    mock_bound.bind = MagicMock(return_value=mock_bound)
    mock_llm.bind_tools = MagicMock(return_value=mock_bound)
    mock_llm.bind = MagicMock(return_value=mock_bound)
    return mock_llm, captured_prompts


# ═════════════════════════════════════════════════════════════════════════
# Property 2: Preservation — Successful Cloud Calls Use Anonymized Input
#              and Non-Cloud Routes Skip Anonymization
#
# **Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.5**
#
# On UNFIXED code, these tests MUST PASS — they capture the existing
# correct behavior that must not regress when the fix is applied.
# ═════════════════════════════════════════════════════════════════════════


class TestPreservationCloudAnonymization:
    """
    Preservation tests verifying that existing correct behaviors are maintained.

    **Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.5**
    """

    @given(filler=filler_text_st)
    @settings(max_examples=20, deadline=60000)
    @pytest.mark.asyncio
    async def test_successful_cloud_receives_anonymized_input_and_response_is_deanonymized(
        self, filler: str,
    ):
        """
        Property: For all successful cloud calls with anonymization enabled,
        the cloud LLM's ainvoke receives messages containing placeholder tokens
        (not raw PII), and the returned response content has PII restored via
        deanonymization.

        **Validates: Requirements 3.1**
        """
        pii_text = _build_pii_message(filler)
        state = _make_state(pii_text)
        profile = _mock_profile()

        # Cloud LLM succeeds — response contains placeholders that should be deanonymized
        cloud_llm, captured_prompts = _make_capturing_cloud_llm(
            response_content=f"Hello [NAME_1], your email is [EMAIL_1] and path is [PATH_1]"
        )

        async def _get_cloud_llm():
            return cloud_llm

        async def _get_medium_llm(variant="default"):
            raise AssertionError("Medium LLM should not be called for successful cloud")

        with patch("src.agent.nodes.complex.get_cloud_llm", side_effect=_get_cloud_llm), \
             patch("src.agent.nodes.complex.get_medium_llm", side_effect=_get_medium_llm), \
             patch("src.agent.nodes.complex.get_profile", return_value=profile):
            from src.agent.nodes.complex import complex_llm_node
            result = await complex_llm_node(state)

        # Cloud LLM must have been called
        assert len(captured_prompts) > 0, "Cloud LLM was never called"

        # The cloud LLM should have received anonymized input with placeholders
        cloud_text = _extract_all_text_from_messages(captured_prompts[0])
        placeholders_found = PLACEHOLDER_RE.findall(cloud_text)
        assert len(placeholders_found) > 0, (
            f"Cloud LLM did NOT receive anonymized input — no placeholders found. "
            f"Expected [NAME_1], [EMAIL_1], [PATH_1] etc."
        )

        # The original PII should NOT be in the cloud input
        for pii_value in KNOWN_PII:
            assert pii_value not in cloud_text, (
                f"Cloud LLM received raw PII {pii_value!r} — anonymization failed"
            )

        # The returned response should be deanonymized (PII restored)
        response_msgs = result["messages"]
        response_text = _extract_all_text_from_messages(response_msgs)

        # Response should contain original PII (deanonymized)
        assert KNOWN_NAME in response_text, (
            f"Response not deanonymized — missing {KNOWN_NAME!r}"
        )
        assert KNOWN_EMAIL in response_text, (
            f"Response not deanonymized — missing {KNOWN_EMAIL!r}"
        )

    @given(filler=filler_text_st, route=non_cloud_route_st)
    @settings(max_examples=20, deadline=60000)
    @pytest.mark.asyncio
    async def test_non_cloud_routes_skip_anonymization(
        self, filler: str, route: str,
    ):
        """
        Property: For all non-cloud routes (complex-default, complex-vision,
        complex-longctx), anonymize is never invoked and the LLM receives
        original messages unchanged.

        **Validates: Requirements 3.3, 3.5**
        """
        pii_text = _build_pii_message(filler)
        state = _make_state_with_route(pii_text, route)
        profile = _mock_profile()  # anonymization enabled, but route is non-cloud

        local_llm, captured_prompts = _make_capturing_local_llm()

        async def _get_medium_llm(variant="default"):
            return local_llm

        with patch("src.agent.nodes.complex.get_medium_llm", side_effect=_get_medium_llm), \
             patch("src.agent.nodes.complex.get_profile", return_value=profile), \
             patch("src.agent.anonymization.anonymize", wraps=__import__("src.agent.anonymization", fromlist=["anonymize"]).anonymize) as mock_anon:
            from src.agent.nodes.complex import complex_llm_node
            result = await complex_llm_node(state)

        # anonymize should never have been called
        assert mock_anon.call_count == 0, (
            f"anonymize was called {mock_anon.call_count} times for non-cloud route {route!r} — "
            f"it should never be called for non-cloud routes"
        )

        # The local LLM must have been called
        assert len(captured_prompts) > 0, (
            f"Local LLM was never called for route={route!r}"
        )

        # The local LLM should have received original PII (no placeholders)
        local_text = _extract_all_text_from_messages(captured_prompts[0])
        for pii_value in KNOWN_PII:
            assert pii_value in local_text, (
                f"Local LLM input missing original PII {pii_value!r} for route={route!r}"
            )

        # No placeholders should be present
        placeholders_found = PLACEHOLDER_RE.findall(local_text)
        assert len(placeholders_found) == 0, (
            f"Local LLM received placeholder tokens {placeholders_found} for route={route!r}"
        )

    @given(filler=filler_text_st)
    @settings(max_examples=20, deadline=60000)
    @pytest.mark.asyncio
    async def test_cloud_route_anon_disabled_skips_anonymization(
        self, filler: str,
    ):
        """
        Property: For cloud route with cloud_anonymization_enabled=False,
        anonymize is never invoked.

        **Validates: Requirements 3.2**
        """
        pii_text = _build_pii_message(filler)
        state = _make_state(pii_text)  # route=complex-cloud
        profile = _mock_profile_anon_disabled()

        cloud_llm, captured_prompts = _make_capturing_cloud_llm(
            response_content="Here is your answer."
        )

        async def _get_cloud_llm():
            return cloud_llm

        async def _get_medium_llm(variant="default"):
            raise AssertionError("Medium LLM should not be called for successful cloud")

        with patch("src.agent.nodes.complex.get_cloud_llm", side_effect=_get_cloud_llm), \
             patch("src.agent.nodes.complex.get_medium_llm", side_effect=_get_medium_llm), \
             patch("src.agent.nodes.complex.get_profile", return_value=profile), \
             patch("src.agent.anonymization.anonymize", wraps=__import__("src.agent.anonymization", fromlist=["anonymize"]).anonymize) as mock_anon:
            from src.agent.nodes.complex import complex_llm_node
            result = await complex_llm_node(state)

        # anonymize should never have been called
        assert mock_anon.call_count == 0, (
            f"anonymize was called {mock_anon.call_count} times with cloud_anonymization_enabled=False — "
            f"it should never be called when anonymization is disabled"
        )

        # Cloud LLM should have received original PII
        assert len(captured_prompts) > 0, "Cloud LLM was never called"
        cloud_text = _extract_all_text_from_messages(captured_prompts[0])
        for pii_value in KNOWN_PII:
            assert pii_value in cloud_text, (
                f"Cloud LLM input missing original PII {pii_value!r} with anon disabled"
            )

    @given(filler=filler_text_st)
    @settings(max_examples=20, deadline=60000)
    @pytest.mark.asyncio
    async def test_successful_cloud_tool_calls_are_deanonymized(
        self, filler: str,
    ):
        """
        Property: For successful cloud responses with tool calls containing
        anonymized args, the returned tool call args are deanonymized.

        **Validates: Requirements 3.4**
        """
        pii_text = _build_pii_message(filler)
        state = _make_state(pii_text)
        profile = _mock_profile()

        # We need to know what the anonymization mapping will be so we can
        # construct a realistic cloud response with anonymized tool call args.
        # Run anonymize on the PII text to get the mapping.
        from src.agent.anonymization import anonymize as real_anonymize
        anon_ctx = {
            "name": profile.get("name", ""),
            "custom_sensitive_terms": profile.get("custom_sensitive_terms", []),
        }
        _, expected_mapping = real_anonymize(pii_text, anon_ctx)

        # The cloud LLM returns tool calls with anonymized args
        # Use placeholders that the anonymization would produce
        cloud_llm, captured_prompts = _make_capturing_cloud_llm_with_tool_calls(expected_mapping)

        async def _get_cloud_llm():
            return cloud_llm

        async def _get_medium_llm(variant="default"):
            raise AssertionError("Medium LLM should not be called for successful cloud")

        with patch("src.agent.nodes.complex.get_cloud_llm", side_effect=_get_cloud_llm), \
             patch("src.agent.nodes.complex.get_medium_llm", side_effect=_get_medium_llm), \
             patch("src.agent.nodes.complex.get_profile", return_value=profile):
            from src.agent.nodes.complex import complex_llm_node
            result = await complex_llm_node(state)

        # The response should have tool calls
        response_msgs = result["messages"]
        tool_call_msgs = [
            m for m in response_msgs
            if isinstance(m, AIMessage) and getattr(m, "tool_calls", None)
        ]
        assert len(tool_call_msgs) > 0, "No tool call messages in response"

        # Tool call args should be deanonymized — no placeholders remaining
        for msg in tool_call_msgs:
            for tc in msg.tool_calls:
                args_str = str(tc.get("args", {}))
                placeholders_in_args = PLACEHOLDER_RE.findall(args_str)
                assert len(placeholders_in_args) == 0, (
                    f"Tool call args still contain placeholders {placeholders_in_args} — "
                    f"deanonymization of tool call args failed. Args: {tc['args']}"
                )


def test_auth_fallback_preserves_original_input_and_emits_auth_note():
    """
    Regression guard for auth-error cloud fallback:
    - fallback prompt must use original non-anonymized content
    - response should include auth guidance note
    """
    pii_text = _build_pii_message("please help now")
    state = _make_state(pii_text)
    profile = _mock_profile()

    cloud_llm = _make_cloud_llm_that_raises("auth_401")
    fallback_llm, captured_prompts = _make_capturing_fallback_llm()

    async def _get_cloud_llm():
        return cloud_llm

    async def _get_medium_llm(variant="default"):
        return fallback_llm

    async def _run():
        with patch("src.agent.nodes.complex.get_cloud_llm", side_effect=_get_cloud_llm), \
             patch("src.agent.nodes.complex.get_medium_llm", side_effect=_get_medium_llm), \
             patch("src.agent.nodes.complex.get_profile", return_value=profile):
            from src.agent.nodes.complex import complex_llm_node
            return await complex_llm_node(state)

    result = asyncio.run(_run())

    assert captured_prompts, "Fallback LLM should be used on auth cloud failure"
    fallback_text = _extract_all_text_from_messages(captured_prompts[0])
    assert KNOWN_NAME in fallback_text
    assert KNOWN_EMAIL in fallback_text
    assert KNOWN_PATH in fallback_text
    assert PLACEHOLDER_RE.search(fallback_text) is None

    output_text = _extract_all_text_from_messages(result["messages"])
    assert "DeepSeek API key may be invalid" in output_text


@pytest.mark.parametrize("error_type", ["rate_limit_429", "generic_error"])
def test_non_auth_cloud_fallback_preserves_original_input(error_type: str):
    """
    Regression guard for non-auth cloud fallback branches (429/generic):
    fallback prompt must use original non-anonymized content.
    """
    pii_text = _build_pii_message("fallback branch validation")
    state = _make_state(pii_text)
    profile = _mock_profile()

    cloud_llm = _make_cloud_llm_that_raises(error_type)
    fallback_llm, captured_prompts = _make_capturing_fallback_llm()

    async def _get_cloud_llm():
        return cloud_llm

    async def _get_medium_llm(variant="default"):
        return fallback_llm

    async def _run():
        with patch("src.agent.nodes.complex.get_cloud_llm", side_effect=_get_cloud_llm), \
             patch("src.agent.nodes.complex.get_medium_llm", side_effect=_get_medium_llm), \
             patch("src.agent.nodes.complex.get_profile", return_value=profile), \
             patch("src.agent.nodes.complex.asyncio.sleep", new_callable=AsyncMock):
            from src.agent.nodes.complex import complex_llm_node
            return await complex_llm_node(state)

    result = asyncio.run(_run())

    assert captured_prompts, f"Fallback LLM should be used for {error_type}"
    fallback_text = _extract_all_text_from_messages(captured_prompts[0])
    assert KNOWN_NAME in fallback_text
    assert KNOWN_EMAIL in fallback_text
    assert KNOWN_PATH in fallback_text
    assert PLACEHOLDER_RE.search(fallback_text) is None

    # Non-auth fallback should not append auth-specific guidance.
    output_text = _extract_all_text_from_messages(result["messages"])
    assert "DeepSeek API key may be invalid" not in output_text
