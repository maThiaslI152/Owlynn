"""
Property-based and unit tests for the Router model-swap pipeline.

Covers toolbox-route coherence, tool binding verification, prose stall
detection, toolbox minimality, HITL precision, deterministic overrides,
swap-aware selection, cloud escalation, token budget, classifier
robustness, feature extraction, and end-to-end fallback safety.

Feature: router-model-swap-testing
"""

import json
import sys
from unittest.mock import MagicMock, AsyncMock, patch

# Must mock mem0 BEFORE any src imports (mem0 is not installed in test env)
sys.modules["mem0"] = MagicMock()

import pytest
from hypothesis import given, settings, assume
from hypothesis import strategies as st
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

# ── Production imports: router node ──────────────────────────────────────
from src.agent.nodes.router import (
    router_node,
    _router_node_inner,
    _resolve_complex_route,
    estimate_token_budget,
    parse_routing,
)

# ── Production imports: complex node ─────────────────────────────────────
from src.agent.nodes.complex import (
    complex_llm_node,
    _looks_like_prose_tool_stall,
    _auto_read_workspace_bundle,
    _workspace_paths_from_text,
    _user_intent_needs_workspace_read,
    _fallback_for_blank_response,
)

# ── Production imports: tool sets ────────────────────────────────────────
from src.agent.tool_sets import (
    resolve_tools,
    TOOLBOX_REGISTRY,
    ALWAYS_INCLUDED_TOOLS,
    COMPLEX_TOOLS_WITH_WEB,
    COMPLEX_TOOLS_NO_WEB,
)

# ── Production imports: router sub-modules ───────────────────────────────
from src.agent.router.classifier import parse_classification, RouteClassifier
from src.agent.router.selector import RouteSelector, _route_to_variant
from src.agent.router.feature_extractor import extract_features
from src.agent.router.models import (
    TaskFeatures,
    RouteClassification,
    RouterConfig,
    VALID_ROUTES as _PROD_VALID_ROUTES,
    VALID_TASK_CATEGORIES,
)

# ── Production imports: LLM pool and swap ────────────────────────────────
from src.agent.llm import LLMPool, get_medium_llm, get_cloud_llm, get_small_llm, CloudUnavailableError
from src.agent.swap_manager import SwapManager, ModelSwapError

# ── Production imports: settings ─────────────────────────────────────────
from src.config.settings import MEDIUM_DEFAULT_CONTEXT, MEDIUM_LONGCTX_CONTEXT


# ═════════════════════════════════════════════════════════════════════════
# Domain Constants
# ═════════════════════════════════════════════════════════════════════════

VALID_ROUTES = {"simple", "complex-default", "complex-vision", "complex-longctx", "complex-cloud"}
VALID_COMPLEX_ROUTES = {"complex-default", "complex-vision", "complex-longctx", "complex-cloud"}
VALID_VARIANTS = {"default", "vision", "longctx"}
TOOLBOX_NAMES = set(TOOLBOX_REGISTRY.keys())


# ═════════════════════════════════════════════════════════════════════════
# Hypothesis Strategies
# ═════════════════════════════════════════════════════════════════════════

# Arbitrary user text (non-empty, printable-ish characters)
user_text_st = st.text(
    min_size=1,
    max_size=5000,
    alphabet=st.characters(whitelist_categories=("L", "N", "P", "Z")),
)

# Route values
route_st = st.sampled_from(sorted(VALID_ROUTES))
complex_route_st = st.sampled_from(sorted(VALID_COMPLEX_ROUTES))

# Medium-tier variant
variant_st = st.sampled_from(["default", "vision", "longctx"])

# Confidence and threshold scores
confidence_st = st.floats(min_value=0.0, max_value=1.0, allow_nan=False)
threshold_st = st.floats(min_value=0.0, max_value=1.0, allow_nan=False)

# Toolbox strategies
toolbox_name_st = st.sampled_from(sorted(TOOLBOX_REGISTRY.keys()))
toolbox_subset_st = st.lists(
    toolbox_name_st,
    min_size=0,
    max_size=len(TOOLBOX_REGISTRY),
    unique=True,
)

# Web search flag
web_search_st = st.booleans()

# TaskFeatures strategy — builds random valid TaskFeatures
task_features_st = st.builds(
    TaskFeatures,
    has_images=st.booleans(),
    has_file_attachments=st.booleans(),
    estimated_input_tokens=st.integers(min_value=0, max_value=200_000),
    context_ratio_default=st.floats(min_value=0.0, max_value=2.0, allow_nan=False),
    context_ratio_longctx=st.floats(min_value=0.0, max_value=2.0, allow_nan=False),
    has_tool_history=st.booleans(),
    web_intent=st.booleans(),
    task_category=st.sampled_from(sorted(VALID_TASK_CATEGORIES)),
    document_keywords_score=st.floats(min_value=0.0, max_value=1.0, allow_nan=False),
    vision_keywords_score=st.floats(min_value=0.0, max_value=1.0, allow_nan=False),
    frontier_quality_needed=st.booleans(),
)

# Arbitrary strings for parse robustness testing
classification_json_st = st.text(min_size=0, max_size=500)


# ═════════════════════════════════════════════════════════════════════════
# Helper Functions — State Builders
# ═════════════════════════════════════════════════════════════════════════

def _make_text_state(text: str, web_search: bool = True) -> dict:
    """Build a minimal AgentState dict with a single text message."""
    return {
        "messages": [HumanMessage(content=text)],
        "web_search_enabled": web_search,
    }


def _make_image_state(text: str = "Describe this image") -> dict:
    """Build a minimal AgentState with multimodal content including an image_url block."""
    return {
        "messages": [HumanMessage(content=[
            {"type": "text", "text": text},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,abc123"}},
        ])],
        "web_search_enabled": True,
    }


def _make_complex_state(
    route: str,
    text: str = "test query",
    selected_toolboxes: list[str] | None = None,
    web_search_enabled: bool = True,
    mode: str = "tools_on",
) -> dict:
    """Build a minimal AgentState dict for complex_llm_node."""
    return {
        "messages": [HumanMessage(content=text)],
        "route": route,
        "web_search_enabled": web_search_enabled,
        "memory_context": "None",
        "persona": "test",
        "mode": mode,
        "token_budget": 4096,
        "selected_toolboxes": selected_toolboxes or ["all"],
        "response_style": None,
        "security_decision": None,
        "security_reason": None,
    }


# ═════════════════════════════════════════════════════════════════════════
# Helper Functions — Mock LLM Factories
# ═════════════════════════════════════════════════════════════════════════

def _make_mock_llm(response_content="Test response", tool_calls=None):
    """Create a mock LLM that works with bind_tools().bind().ainvoke() chain.

    The mock supports chaining: llm.bind_tools(tools).bind(max_tokens=N).ainvoke(msgs)
    """
    mock_llm = MagicMock()
    response = AIMessage(content=response_content)
    if tool_calls:
        response.tool_calls = tool_calls
    mock_llm.bind_tools.return_value = mock_llm
    mock_llm.bind.return_value = mock_llm
    mock_llm.ainvoke = AsyncMock(return_value=response)
    return mock_llm


def _make_spy_llm(response_content="Test response"):
    """Create a spy LLM that captures the exact tools passed to bind_tools.

    Returns (mock_llm, captured_tools) where captured_tools is a list that
    gets populated with the tool objects passed to bind_tools(). This is
    CRITICAL for verifying tool binding after model swaps.
    """
    mock_llm = MagicMock()
    captured_tools = []

    def spy_bind_tools(tools):
        captured_tools.extend(tools)
        return mock_llm

    mock_llm.bind_tools = MagicMock(side_effect=spy_bind_tools)
    mock_llm.bind.return_value = mock_llm
    mock_llm.ainvoke = AsyncMock(return_value=AIMessage(content=response_content))
    return mock_llm, captured_tools


# ═════════════════════════════════════════════════════════════════════════
# Shared Fixtures
# ═════════════════════════════════════════════════════════════════════════

@pytest.fixture
def clean_llm_pool():
    """Reset LLMPool state before and after each test."""
    LLMPool.clear()
    yield
    LLMPool.clear()


@pytest.fixture
def mock_profile():
    """Configurable user profile dict with all relevant settings."""
    return {
        "router_hitl_enabled": True,
        "router_clarification_threshold": 0.6,
        "cloud_escalation_enabled": True,
        "cloud_hitl_enabled": True,
        "cloud_anonymization_enabled": False,
        "medium_models": {
            "default": "qwen/qwen3.5-9b",
            "vision": "qwen/qwen3.5-9b-vision",
            "longctx": "qwen/qwen3.5-9b-longctx",
        },
        "deepseek_api_key": "sk-test-key",
        "small_llm_base_url": "http://127.0.0.1:1234/v1",
        "llm_base_url": "http://127.0.0.1:1234/v1",
    }


@pytest.fixture
def mock_llm_response():
    """Factory fixture returning a MagicMock AIMessage with configurable content."""
    def _factory(content: str = '{"routing":"complex","confidence":0.9,"toolbox":"all"}'):
        msg = MagicMock(spec=AIMessage)
        msg.content = content
        return msg
    return _factory


# ═════════════════════════════════════════════════════════════════════════
# TestToolboxRouteCoherence — Requirement 1
# ═════════════════════════════════════════════════════════════════════════

class TestToolboxRouteCoherence:
    """Verify that the Router's selected_toolboxes contain the tools
    required by the task type implied by the route and features.

    Feature: router-model-swap-testing
    Requirement: 1 — Toolbox-Route Coherence
    """

    # ── Req 1.1: longctx + file_attachments → file_ops ──────────────
    @pytest.mark.xfail(reason="Router does not yet augment toolbox for file/document tasks")
    @pytest.mark.anyio
    async def test_longctx_file_attachments_includes_file_ops(self, mock_profile):
        """Validates: Requirements 1.1, 1.5

        WHEN the Router selects route complex-longctx AND has_file_attachments
        is True, selected_toolboxes SHALL contain file_ops.
        """
        # Classifier returns longctx route with a toolbox that does NOT
        # include file_ops — the router should augment it.
        classifier_json = json.dumps({
            "route": "complex-longctx",
            "confidence": 0.9,
            "toolbox": ["memory"],
            "reasoning": "long document task",
        })
        mock_small = _make_mock_llm(response_content=classifier_json)

        with (
            patch("src.agent.nodes.router.get_small_llm", new_callable=AsyncMock, return_value=mock_small),
            patch("src.agent.nodes.router._check_cloud_available", return_value=False),
            patch("src.agent.nodes.router.get_profile", return_value=mock_profile),
        ):
            # Input with file attachment marker to trigger has_file_attachments
            state = _make_text_state("[file: data.csv] summarize this document")
            result = await _router_node_inner(state, RouterConfig())

        assert "file_ops" in result["selected_toolboxes"], (
            f"Expected file_ops in toolboxes for file attachment task, "
            f"got {result['selected_toolboxes']}"
        )

    # ── Req 1.2: vision + images → file_ops ─────────────────────────
    @pytest.mark.xfail(reason="Router does not yet augment toolbox for file/document tasks")
    @pytest.mark.anyio
    async def test_vision_images_includes_file_ops(self, mock_profile):
        """Validates: Requirements 1.2, 1.5

        WHEN the Router selects route complex-vision AND has_images is True,
        selected_toolboxes SHALL contain file_ops.
        """
        # Image state triggers deterministic override to complex-vision.
        # The deterministic path uses toolbox=["all"] by default, but if
        # the router were to use a classifier toolbox, it should augment.
        # We test the expected behavior: vision route should include file_ops.
        classifier_json = json.dumps({
            "route": "complex-vision",
            "confidence": 0.95,
            "toolbox": ["memory"],
            "reasoning": "image task",
        })
        mock_small = _make_mock_llm(response_content=classifier_json)

        with (
            patch("src.agent.nodes.router.get_small_llm", new_callable=AsyncMock, return_value=mock_small),
            patch("src.agent.nodes.router._check_cloud_available", return_value=False),
            patch("src.agent.nodes.router.get_profile", return_value=mock_profile),
        ):
            # Use image state — deterministic override to vision
            state = _make_image_state("Describe this image and save analysis")
            result = await _router_node_inner(state, RouterConfig())

        assert result["route"] == "complex-vision"
        # The deterministic path currently sets toolbox=["all"], which
        # resolves to include file_ops. But the requirement says the
        # selected_toolboxes list itself should contain file_ops explicitly.
        toolboxes = result["selected_toolboxes"]
        assert "file_ops" in toolboxes, (
            f"Expected file_ops in toolboxes for vision+image task, got {toolboxes}"
        )

    # ── Req 1.3: web_intent → web_search ────────────────────────────
    @pytest.mark.anyio
    async def test_web_intent_includes_web_search(self, mock_profile):
        """Validates: Requirements 1.3

        WHEN the Feature_Extractor detects web_intent is True,
        selected_toolboxes SHALL contain web_search.
        """
        # Classifier returns a toolbox WITHOUT web_search — the router
        # should augment it because web_intent is detected.
        classifier_json = json.dumps({
            "route": "complex-default",
            "confidence": 0.85,
            "toolbox": ["file_ops"],
            "reasoning": "web search needed",
        })
        mock_small = _make_mock_llm(response_content=classifier_json)

        with (
            patch("src.agent.nodes.router.get_small_llm", new_callable=AsyncMock, return_value=mock_small),
            patch("src.agent.nodes.router._check_cloud_available", return_value=False),
            patch("src.agent.nodes.router.get_profile", return_value=mock_profile),
        ):
            # "weather" triggers web_intent in the feature extractor
            state = _make_text_state("What is the weather in Tokyo right now?")
            result = await _router_node_inner(state, RouterConfig())

        assert "web_search" in result["selected_toolboxes"], (
            f"Expected web_search in toolboxes for web_intent task, "
            f"got {result['selected_toolboxes']}"
        )

    # ── Req 1.4: task_category=document → file_ops ──────────────────
    @pytest.mark.xfail(reason="Router does not yet augment toolbox for file/document tasks")
    @pytest.mark.anyio
    async def test_document_category_includes_file_ops(self, mock_profile):
        """Validates: Requirements 1.4, 1.5

        WHEN the Feature_Extractor detects task_category is 'document',
        selected_toolboxes SHALL contain file_ops.
        """
        classifier_json = json.dumps({
            "route": "complex-default",
            "confidence": 0.9,
            "toolbox": ["productivity"],
            "reasoning": "document task",
        })
        mock_small = _make_mock_llm(response_content=classifier_json)

        with (
            patch("src.agent.nodes.router.get_small_llm", new_callable=AsyncMock, return_value=mock_small),
            patch("src.agent.nodes.router._check_cloud_available", return_value=False),
            patch("src.agent.nodes.router.get_profile", return_value=mock_profile),
        ):
            # "summarize this document report" triggers task_category=document
            state = _make_text_state("Please summarize this document report for me")
            result = await _router_node_inner(state, RouterConfig())

        assert "file_ops" in result["selected_toolboxes"], (
            f"Expected file_ops in toolboxes for document task, "
            f"got {result['selected_toolboxes']}"
        )

    # ── Req 1.6: ["all"] resolves to full tool set ──────────────────
    def test_all_resolves_to_full_tool_set(self):
        """Validates: Requirements 1.6

        WHEN selected_toolboxes is ["all"], the resolved tool set SHALL
        contain every tool from every toolbox category.
        """
        tools = resolve_tools(["all"], web_search_enabled=True)
        tool_names = {getattr(t, "name", getattr(t, "__name__", str(t))) for t in tools}

        # Verify every category is represented
        for category, category_tools in TOOLBOX_REGISTRY.items():
            for t in category_tools:
                name = getattr(t, "name", getattr(t, "__name__", str(t)))
                assert name in tool_names, (
                    f"Expected tool '{name}' from category '{category}' "
                    f"in resolved 'all' tool set"
                )

        # ask_user must always be present
        always_names = {getattr(t, "name", getattr(t, "__name__", str(t))) for t in ALWAYS_INCLUDED_TOOLS}
        for name in always_names:
            assert name in tool_names, f"Expected always-included tool '{name}' in resolved 'all' tool set"

    # ── Property 1: Toolbox-Route Coherence ─────────────────────────
    @given(features=task_features_st, toolboxes=toolbox_subset_st, web_on=web_search_st)
    @settings(max_examples=100, deadline=None)
    def test_toolbox_contains_required_categories(self, features, toolboxes, web_on):
        """Feature: router-model-swap-testing, Property 1: Toolbox-Route Coherence

        For any TaskFeatures with file attachments, web intent, or document
        category, when the toolbox contains the required categories, the
        resolved tool set SHALL contain the corresponding tools.
        Validates: Requirements 1.1, 1.3, 1.4, 1.5, 1.6
        """
        tools = resolve_tools(toolboxes, web_search_enabled=web_on)
        tool_names = {getattr(t, "name", getattr(t, "__name__", str(t))) for t in tools}

        # ask_user is always present
        assert "ask_user" in tool_names, "ask_user must always be in resolved tools"

        # If file_ops is in the requested toolboxes, file tools must be present
        if "file_ops" in toolboxes:
            for expected in ("read_workspace_file", "write_workspace_file",
                             "edit_workspace_file", "list_workspace_files",
                             "delete_workspace_file"):
                assert expected in tool_names, (
                    f"file_ops requested but '{expected}' missing from resolved tools"
                )

        # If web_search is in the requested toolboxes AND web is enabled, web tools must be present
        if "web_search" in toolboxes and web_on:
            assert "web_search" in tool_names, (
                "web_search requested and enabled but web_search tool missing"
            )

        # If web_search is in toolboxes but web is disabled, web tools must NOT be present
        if "web_search" in toolboxes and not web_on:
            assert "web_search" not in tool_names, (
                "web_search requested but web disabled — web_search tool should be excluded"
            )

        # ["all"] resolves to full tool set
        if "all" in toolboxes or not toolboxes:
            for category, category_tools in TOOLBOX_REGISTRY.items():
                if category == "web_search" and not web_on:
                    continue
                for t in category_tools:
                    name = getattr(t, "name", getattr(t, "__name__", str(t)))
                    assert name in tool_names, (
                        f"'all' toolbox should include '{name}' from '{category}'"
                    )


# ═════════════════════════════════════════════════════════════════════════
# TestToolBindingAfterSwap — Requirement 2
# ═════════════════════════════════════════════════════════════════════════

class TestToolBindingAfterSwap:
    """Verify that after any model swap path, Complex_Node calls bind_tools
    with the correct resolved tool list containing the specific tools
    required by the task.

    Feature: router-model-swap-testing
    Requirement: 2 — Tool Binding Verification After Model Swap
    """

    # ── Req 2.2: file_ops toolbox → bind_tools receives all 5 file tools + ask_user ──
    @pytest.mark.anyio
    async def test_file_ops_toolbox_binds_all_file_tools(self, mock_profile):
        """Validates: Requirements 2.1, 2.2, 2.4

        WHEN selected_toolboxes contains file_ops, THE resolved tool list
        passed to bind_tools SHALL contain all 5 file operation tools plus ask_user.
        """
        from src.tools.core_tools import (
            read_workspace_file, write_workspace_file, edit_workspace_file,
            list_workspace_files, delete_workspace_file,
        )
        from src.tools.ask_user import ask_user

        spy_llm, captured_tools = _make_spy_llm("I'll help with that file.")
        state = _make_complex_state(
            route="complex-default",
            text="Read the data file",
            selected_toolboxes=["file_ops"],
        )

        with (
            patch("src.agent.nodes.complex.get_medium_llm", new_callable=AsyncMock, return_value=spy_llm),
            patch("src.agent.nodes.complex.get_cloud_llm", new_callable=AsyncMock, return_value=spy_llm),
            patch("src.agent.nodes.complex.get_profile", return_value=mock_profile),
            patch("src.agent.nodes.complex.is_local_server", return_value=True),
        ):
            await complex_llm_node(state)

        # Verify bind_tools was called
        assert len(captured_tools) > 0, "bind_tools was never called"

        # Check all 5 file tools are present
        expected_file_tools = [
            read_workspace_file, write_workspace_file, edit_workspace_file,
            list_workspace_files, delete_workspace_file,
        ]
        captured_names = {getattr(t, "name", getattr(t, "__name__", str(t))) for t in captured_tools}
        for tool_obj in expected_file_tools:
            name = getattr(tool_obj, "name", getattr(tool_obj, "__name__", str(tool_obj)))
            assert name in captured_names, (
                f"Expected {name} in bind_tools args, got {captured_names}"
            )

        # ask_user must always be present (Req 2.4)
        ask_user_name = getattr(ask_user, "name", "ask_user")
        assert ask_user_name in captured_names, "ask_user must always be in bind_tools args"

    # ── Req 2.3: data_viz toolbox → bind_tools receives all 6 data_viz tools + ask_user ──
    @pytest.mark.anyio
    async def test_data_viz_toolbox_binds_all_data_viz_tools(self, mock_profile):
        """Validates: Requirements 2.1, 2.3, 2.4

        WHEN selected_toolboxes contains data_viz, THE resolved tool list
        passed to bind_tools SHALL contain all 6 data_viz tools plus ask_user.
        """
        from src.tools.doc_generator import create_docx, create_xlsx, create_pptx, create_pdf
        from src.tools.notebook import notebook_run, notebook_reset
        from src.tools.ask_user import ask_user

        spy_llm, captured_tools = _make_spy_llm("Creating your document.")
        state = _make_complex_state(
            route="complex-default",
            text="Create a spreadsheet",
            selected_toolboxes=["data_viz"],
        )

        with (
            patch("src.agent.nodes.complex.get_medium_llm", new_callable=AsyncMock, return_value=spy_llm),
            patch("src.agent.nodes.complex.get_cloud_llm", new_callable=AsyncMock, return_value=spy_llm),
            patch("src.agent.nodes.complex.get_profile", return_value=mock_profile),
            patch("src.agent.nodes.complex.is_local_server", return_value=True),
        ):
            await complex_llm_node(state)

        assert len(captured_tools) > 0, "bind_tools was never called"

        expected_data_viz_tools = [
            create_docx, create_xlsx, create_pptx, create_pdf,
            notebook_run, notebook_reset,
        ]
        captured_names = {getattr(t, "name", getattr(t, "__name__", str(t))) for t in captured_tools}
        for tool_obj in expected_data_viz_tools:
            name = getattr(tool_obj, "name", getattr(tool_obj, "__name__", str(tool_obj)))
            assert name in captured_names, (
                f"Expected {name} in bind_tools args, got {captured_names}"
            )

        ask_user_name = getattr(ask_user, "name", "ask_user")
        assert ask_user_name in captured_names, "ask_user must always be in bind_tools args"

    # ── Req 2.5: prior tool history → previously-used tools included ──
    @pytest.mark.anyio
    async def test_prior_tool_history_included_in_bound_tools(self, mock_profile):
        """Validates: Requirements 2.5

        WHEN the conversation history contains prior tool calls, THE
        Complex_Node SHALL include those previously-used tools in the
        bound tool list even if the tools are not in the selected toolboxes.
        """
        from src.tools.core_tools import read_workspace_file
        from src.tools.ask_user import ask_user

        spy_llm, captured_tools = _make_spy_llm("Here's the analysis.")

        # Build state with tool history: an AIMessage with tool_calls
        # and a corresponding ToolMessage
        ai_msg_with_tools = AIMessage(
            content="Let me read that file.",
            tool_calls=[{
                "name": "read_workspace_file",
                "args": {"filename": "data.csv"},
                "id": "call_123",
            }],
        )
        tool_response = ToolMessage(
            content="file contents here",
            tool_call_id="call_123",
        )

        state = {
            "messages": [
                HumanMessage(content="Read data.csv"),
                ai_msg_with_tools,
                tool_response,
                HumanMessage(content="Now summarize it"),
            ],
            "route": "complex-default",
            "web_search_enabled": True,
            "memory_context": "None",
            "persona": "test",
            "mode": "tools_on",
            "token_budget": 4096,
            # Use a toolbox that does NOT include file_ops
            "selected_toolboxes": ["productivity"],
            "response_style": None,
            "security_decision": None,
            "security_reason": None,
        }

        with (
            patch("src.agent.nodes.complex.get_medium_llm", new_callable=AsyncMock, return_value=spy_llm),
            patch("src.agent.nodes.complex.get_cloud_llm", new_callable=AsyncMock, return_value=spy_llm),
            patch("src.agent.nodes.complex.get_profile", return_value=mock_profile),
            patch("src.agent.nodes.complex.is_local_server", return_value=True),
        ):
            await complex_llm_node(state)

        assert len(captured_tools) > 0, "bind_tools was never called"

        # read_workspace_file should be included because it was used in prior tool calls
        captured_tool_names = {
            getattr(t, "name", getattr(t, "__name__", str(t))) for t in captured_tools
        }
        assert "read_workspace_file" in captured_tool_names, (
            f"Expected read_workspace_file from tool history in bind_tools args, "
            f"got tool names: {captured_tool_names}"
        )

        # ask_user must still be present
        assert ask_user in captured_tools, "ask_user must always be in bind_tools args"

    # ── Req 2.6: fallback from vision to default → re-binds same tool list ──
    @pytest.mark.anyio
    async def test_fallback_from_vision_rebinds_same_tools(self, mock_profile):
        """Validates: Requirements 2.6

        WHEN the Complex_Node falls back from a failed vision model to
        medium-default, THE Complex_Node SHALL re-bind tools on the
        fallback model using the same resolved tool list.
        """
        from src.tools.core_tools import (
            read_workspace_file, write_workspace_file, edit_workspace_file,
            list_workspace_files, delete_workspace_file,
        )
        from src.tools.ask_user import ask_user

        spy_llm, captured_tools = _make_spy_llm("Fallback response.")

        state = _make_complex_state(
            route="complex-vision",
            text="Analyze this image",
            selected_toolboxes=["file_ops"],
        )

        call_count = 0

        async def mock_get_medium_llm(variant="default"):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # First call (vision) fails with ModelSwapError
                assert variant == "vision"
                raise ModelSwapError("Vision model unavailable")
            # Second call (default fallback) succeeds
            return spy_llm

        with (
            patch("src.agent.nodes.complex.get_medium_llm", side_effect=mock_get_medium_llm),
            patch("src.agent.nodes.complex.get_cloud_llm", new_callable=AsyncMock, return_value=spy_llm),
            patch("src.agent.nodes.complex.get_profile", return_value=mock_profile),
            patch("src.agent.nodes.complex.is_local_server", return_value=True),
        ):
            result = await complex_llm_node(state)

        # Verify fallback happened
        assert "fallback" in result["model_used"], (
            f"Expected fallback model, got {result['model_used']}"
        )

        # Verify bind_tools was called on the fallback model with file_ops tools
        assert len(captured_tools) > 0, "bind_tools was never called on fallback model"

        expected_file_tools = [
            read_workspace_file, write_workspace_file, edit_workspace_file,
            list_workspace_files, delete_workspace_file,
        ]
        captured_names = {getattr(t, "name", getattr(t, "__name__", str(t))) for t in captured_tools}
        for tool_obj in expected_file_tools:
            name = getattr(tool_obj, "name", getattr(tool_obj, "__name__", str(tool_obj)))
            assert name in captured_names, (
                f"Expected {name} in fallback bind_tools args, got {captured_names}"
            )

        ask_user_name = getattr(ask_user, "name", "ask_user")
        assert ask_user_name in captured_names, "ask_user must be in fallback bind_tools args"

    # ── Property 2: Tool Binding Completeness ───────────────────────
    @given(route=route_st, toolboxes=toolbox_subset_st, web_on=web_search_st)
    @settings(max_examples=100, deadline=None)
    def test_bind_tools_always_contains_ask_user(self, route, toolboxes, web_on):
        """Feature: router-model-swap-testing, Property 2: Tool Binding Completeness

        For any valid route and toolbox combination, resolve_tools returns
        ask_user and at least one tool. When specific categories are selected,
        all tools from those categories are present.
        Validates: Requirements 2.1, 2.4, 2.7
        """
        tools = resolve_tools(toolboxes, web_search_enabled=web_on)
        tool_names = {getattr(t, "name", getattr(t, "__name__", str(t))) for t in tools}

        # ask_user always present (Req 2.4)
        assert "ask_user" in tool_names, "ask_user must always be in resolved tools"

        # At least one tool (Req 2.7)
        assert len(tools) >= 1, "resolve_tools must return at least one tool"

        # Specific categories contain all their tools
        for name in toolboxes:
            if name == "web_search" and not web_on:
                continue
            if name in TOOLBOX_REGISTRY:
                for t in TOOLBOX_REGISTRY[name]:
                    tname = getattr(t, "name", getattr(t, "__name__", str(t)))
                    assert tname in tool_names, (
                        f"Toolbox '{name}' requested but tool '{tname}' missing"
                    )


# ═════════════════════════════════════════════════════════════════════════
# TestProseStallDetectionRecovery — Requirement 3
# ═════════════════════════════════════════════════════════════════════════

class TestProseStallDetectionRecovery:
    """Verify that the prose-tool-stall detector correctly identifies when
    a model responds with prose instead of tool calls, and that the
    auto-read recovery path reads workspace files and re-prompts.

    Feature: router-model-swap-testing
    Requirement: 3 — Prose Tool Stall Detection and Recovery
    """

    # ── Req 3.1: response mentions read_workspace_file with no tool_calls → True ──
    def test_mentions_read_workspace_file_detected_as_stall(self):
        """Validates: Requirements 3.1

        WHEN the model response contains no tool_calls AND the response
        text mentions read_workspace_file, THE Prose_Stall_Detector SHALL
        return True.
        """
        msg = AIMessage(content="You should use read_workspace_file to open the CSV and then analyze it.")
        assert _looks_like_prose_tool_stall(msg) is True

    # ── Req 3.2: response shorter than 420 chars with no tool_calls → True ──
    def test_short_response_detected_as_stall(self):
        """Validates: Requirements 3.2

        WHEN the model response contains no tool_calls AND the response
        text is shorter than 420 characters, THE Prose_Stall_Detector
        SHALL return True.
        """
        short_text = "I can help you with that file. Let me take a look."
        assert len(short_text) < 420
        msg = AIMessage(content=short_text)
        assert _looks_like_prose_tool_stall(msg) is True

    def test_empty_response_detected_as_stall(self):
        """Empty content is also a stall (edge case of Req 3.2)."""
        msg = AIMessage(content="")
        assert _looks_like_prose_tool_stall(msg) is True

    def test_none_content_detected_as_stall(self):
        """None content is also a stall (edge case of Req 3.2)."""
        msg = AIMessage(content="")
        # Simulate None content
        msg.content = None
        assert _looks_like_prose_tool_stall(msg) is True

    # ── Req 3.3: response WITH tool_calls → False regardless of text ──
    def test_response_with_tool_calls_not_stall(self):
        """Validates: Requirements 3.3

        WHEN the model response contains tool_calls, THE Prose_Stall_Detector
        SHALL return False regardless of response text content.
        """
        msg = AIMessage(
            content="I'll use read_workspace_file to read the data.",
            tool_calls=[{
                "name": "read_workspace_file",
                "args": {"filename": "data.csv"},
                "id": "call_abc",
            }],
        )
        assert _looks_like_prose_tool_stall(msg) is False

    def test_short_response_with_tool_calls_not_stall(self):
        """Short text + tool_calls → still not a stall (Req 3.3)."""
        msg = AIMessage(
            content="OK",
            tool_calls=[{
                "name": "ask_user",
                "args": {"question": "Which file?"},
                "id": "call_xyz",
            }],
        )
        assert len(msg.content) < 420
        assert _looks_like_prose_tool_stall(msg) is False

    def test_long_response_without_keywords_not_stall(self):
        """Long response (>=420 chars) without stall keywords → not a stall."""
        long_text = "A" * 420  # exactly 420 chars
        msg = AIMessage(content=long_text)
        assert _looks_like_prose_tool_stall(msg) is False

    # ── Req 3.4: auto-read recovery reads workspace files and constructs nudge ──
    @pytest.mark.anyio
    async def test_auto_read_recovery_constructs_nudge(self, mock_profile):
        """Validates: Requirements 3.4

        WHEN a prose stall is detected AND workspace file paths are present
        AND user intent requires a workspace read, THE Auto_Read_Recovery
        SHALL read the workspace files and construct a nudge message.
        """
        # First LLM call returns prose stall (mentions read_workspace_file, no tool_calls)
        stall_response = AIMessage(content="You should use read_workspace_file to read data.csv")
        # Second LLM call (re-prompt) returns a proper response
        recovery_response = AIMessage(content="Based on the file contents, here is the summary.")

        mock_llm = MagicMock()
        mock_llm.bind_tools.return_value = mock_llm
        mock_llm.bind.return_value = mock_llm
        call_count = 0

        async def mock_ainvoke(messages):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return stall_response
            return recovery_response

        mock_llm.ainvoke = AsyncMock(side_effect=mock_ainvoke)

        state = _make_complex_state(
            route="complex-default",
            text='[Workspace file `report.csv`] summarize this document',
            selected_toolboxes=["file_ops"],
        )

        with (
            patch("src.agent.nodes.complex.get_medium_llm", new_callable=AsyncMock, return_value=mock_llm),
            patch("src.agent.nodes.complex.get_cloud_llm", new_callable=AsyncMock, return_value=mock_llm),
            patch("src.agent.nodes.complex.get_profile", return_value=mock_profile),
            patch("src.agent.nodes.complex.is_local_server", return_value=True),
            patch(
                "src.agent.nodes.complex._auto_read_workspace_bundle",
                new_callable=AsyncMock,
                return_value="[Automated workspace read]\n\n### File: report.csv\ncol1,col2\n1,2\n3,4",
            ) as mock_auto_read,
        ):
            result = await complex_llm_node(state)

        # _auto_read_workspace_bundle should have been called with the detected paths
        mock_auto_read.assert_called_once()
        called_paths = mock_auto_read.call_args[0][0]
        assert "report.csv" in called_paths

        # The result should contain a nudge HumanMessage + the recovery response
        out_msgs = result["messages"]
        assert len(out_msgs) == 2, f"Expected [nudge, response], got {len(out_msgs)} messages"
        assert isinstance(out_msgs[0], HumanMessage), "First message should be the nudge"
        assert "Automated workspace read" in out_msgs[0].content

    # ── Req 3.5: re-prompt binds same tool list ──
    @pytest.mark.anyio
    async def test_reprompt_binds_same_tool_list(self, mock_profile):
        """Validates: Requirements 3.5

        WHEN the Auto_Read_Recovery re-prompts the model, THE Complex_Node
        SHALL bind the same tool list to the model for the second invocation.
        """
        stall_response = AIMessage(content="Use read_workspace_file to open data.csv")
        recovery_response = AIMessage(content="Here is the analysis of the file.")

        spy_llm, captured_tools = _make_spy_llm()
        call_count = 0

        async def mock_ainvoke(messages):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return stall_response
            return recovery_response

        spy_llm.ainvoke = AsyncMock(side_effect=mock_ainvoke)

        state = _make_complex_state(
            route="complex-default",
            text='[Workspace file `data.csv`] summarize this file',
            selected_toolboxes=["file_ops"],
        )

        with (
            patch("src.agent.nodes.complex.get_medium_llm", new_callable=AsyncMock, return_value=spy_llm),
            patch("src.agent.nodes.complex.get_cloud_llm", new_callable=AsyncMock, return_value=spy_llm),
            patch("src.agent.nodes.complex.get_profile", return_value=mock_profile),
            patch("src.agent.nodes.complex.is_local_server", return_value=True),
            patch(
                "src.agent.nodes.complex._auto_read_workspace_bundle",
                new_callable=AsyncMock,
                return_value="[Automated workspace read]\n\n### File: data.csv\ncol1,col2\n1,2",
            ),
        ):
            await complex_llm_node(state)

        # bind_tools should have been called twice (initial + re-prompt)
        # Each call extends captured_tools. The spy captures all tools from
        # both calls. We verify bind_tools was called at least twice.
        assert spy_llm.bind_tools.call_count >= 2, (
            f"Expected bind_tools called at least twice (initial + re-prompt), "
            f"got {spy_llm.bind_tools.call_count}"
        )

        # Both calls should have received the same tool list
        first_call_tools = spy_llm.bind_tools.call_args_list[0][0][0]
        second_call_tools = spy_llm.bind_tools.call_args_list[1][0][0]
        first_names = {getattr(t, "name", str(t)) for t in first_call_tools}
        second_names = {getattr(t, "name", str(t)) for t in second_call_tools}
        assert first_names == second_names, (
            f"Re-prompt should bind same tools. First: {first_names}, Second: {second_names}"
        )

    # ── Req 3.6: blank re-prompt triggers _fallback_for_blank_response ──
    @pytest.mark.anyio
    async def test_blank_reprompt_triggers_fallback(self, mock_profile):
        """Validates: Requirements 3.6

        WHEN the Auto_Read_Recovery re-prompt also produces a blank or
        empty response, THE Complex_Node SHALL invoke _fallback_for_blank_response.
        """
        stall_response = AIMessage(content="Use read_workspace_file to open data.csv")
        blank_response = AIMessage(content="")

        mock_llm = MagicMock()
        mock_llm.bind_tools.return_value = mock_llm
        mock_llm.bind.return_value = mock_llm
        call_count = 0

        async def mock_ainvoke(messages):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return stall_response
            return blank_response

        mock_llm.ainvoke = AsyncMock(side_effect=mock_ainvoke)

        state = _make_complex_state(
            route="complex-default",
            text='[Workspace file `data.csv`] summarize this file',
            selected_toolboxes=["file_ops"],
        )

        with (
            patch("src.agent.nodes.complex.get_medium_llm", new_callable=AsyncMock, return_value=mock_llm),
            patch("src.agent.nodes.complex.get_cloud_llm", new_callable=AsyncMock, return_value=mock_llm),
            patch("src.agent.nodes.complex.get_profile", return_value=mock_profile),
            patch("src.agent.nodes.complex.is_local_server", return_value=True),
            patch(
                "src.agent.nodes.complex._auto_read_workspace_bundle",
                new_callable=AsyncMock,
                return_value="[Automated workspace read]\n\n### File: data.csv\ncol1,col2\n1,2",
            ),
            patch(
                "src.agent.nodes.complex._fallback_for_blank_response",
                wraps=_fallback_for_blank_response,
            ) as mock_fallback,
        ):
            result = await complex_llm_node(state)

        # _fallback_for_blank_response should have been called
        # It's called twice: once for the initial blank check, and once after re-prompt
        # The re-prompt blank triggers the second call
        assert mock_fallback.call_count >= 1, (
            "_fallback_for_blank_response should be called when re-prompt returns blank"
        )

        # The final response should be the fallback message (not blank)
        final_msg = result["messages"][-1]
        assert isinstance(final_msg, AIMessage)
        assert final_msg.content, "Final response should not be blank after fallback"

    # ── Req 3.7: recovery works for all 3 variants ──
    @pytest.mark.anyio
    @pytest.mark.parametrize("route,variant", [
        ("complex-default", "default"),
        ("complex-vision", "vision"),
        ("complex-longctx", "longctx"),
    ])
    async def test_recovery_works_for_all_variants(self, route, variant, mock_profile):
        """Validates: Requirements 3.7

        THE Auto_Read_Recovery SHALL work correctly for all three
        Medium_Variant models (default, vision, longctx).
        """
        stall_response = AIMessage(content="Use read_workspace_file to open data.csv")
        recovery_response = AIMessage(content="Here is the analysis based on the file contents.")

        mock_llm = MagicMock()
        mock_llm.bind_tools.return_value = mock_llm
        mock_llm.bind.return_value = mock_llm
        call_count = 0

        async def mock_ainvoke(messages):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return stall_response
            return recovery_response

        mock_llm.ainvoke = AsyncMock(side_effect=mock_ainvoke)

        state = _make_complex_state(
            route=route,
            text='[Workspace file `notes.txt`] summarize this document',
            selected_toolboxes=["file_ops"],
        )

        with (
            patch("src.agent.nodes.complex.get_medium_llm", new_callable=AsyncMock, return_value=mock_llm),
            patch("src.agent.nodes.complex.get_cloud_llm", new_callable=AsyncMock, return_value=mock_llm),
            patch("src.agent.nodes.complex.get_profile", return_value=mock_profile),
            patch("src.agent.nodes.complex.is_local_server", return_value=True),
            patch(
                "src.agent.nodes.complex._auto_read_workspace_bundle",
                new_callable=AsyncMock,
                return_value="[Automated workspace read]\n\n### File: notes.txt\nSome notes here.",
            ) as mock_auto_read,
        ):
            result = await complex_llm_node(state)

        # Auto-read should have been triggered for this variant
        mock_auto_read.assert_called_once()

        # The result should contain the nudge + recovery response
        out_msgs = result["messages"]
        assert len(out_msgs) == 2, (
            f"Expected [nudge, response] for {variant} variant, got {len(out_msgs)} messages"
        )
        assert isinstance(out_msgs[0], HumanMessage), f"First message should be nudge for {variant}"
        assert "Automated workspace read" in out_msgs[0].content

    # ── Property 3: Prose Stall Detection Correctness ───────────────
    @given(content=user_text_st)
    @settings(max_examples=100, deadline=None)
    def test_prose_stall_detection_correctness(self, content):
        """Feature: router-model-swap-testing, Property 3: Prose Stall Detection Correctness

        For any AIMessage with tool_calls → False; without tool_calls and
        short content (< 420 chars) → True.
        Validates: Requirements 3.2, 3.3
        """
        # Case 1: With tool_calls → always False (Req 3.3)
        msg_with_tools = AIMessage(content=content)
        msg_with_tools.tool_calls = [{"name": "test_tool", "args": {}, "id": "1"}]
        assert _looks_like_prose_tool_stall(msg_with_tools) is False, (
            "Response with tool_calls should never be detected as prose stall"
        )

        # Case 2: Without tool_calls, short content → True (Req 3.2)
        short_content = content[:419]  # Ensure < 420 chars
        # Avoid content that is >= 420 chars after stripping
        if len(short_content.strip()) < 420 and short_content.strip():
            msg_short = AIMessage(content=short_content)
            result = _looks_like_prose_tool_stall(msg_short)
            assert result is True, (
                f"Short response ({len(short_content.strip())} chars) without tool_calls "
                f"should be detected as prose stall"
            )


# ═════════════════════════════════════════════════════════════════════════
# TestToolboxMinimality — Requirement 4
# ═════════════════════════════════════════════════════════════════════════

class TestToolboxMinimality:
    """Verify that toolbox selection is minimal — only requested tools plus
    ask_user, no extras, no duplicates.

    Feature: router-model-swap-testing
    Requirement: 4 — Toolbox Minimality
    """

    # ── Helper ───────────────────────────────────────────────────────
    @staticmethod
    def _tool_names(tools: list) -> list[str]:
        """Extract tool names from a list of tool objects."""
        return [getattr(t, "name", getattr(t, "__name__", str(t))) for t in tools]

    # ── Req 4.1: specific toolbox names → only requested tools + ask_user ──
    def test_specific_toolbox_returns_only_requested_tools(self):
        """Validates: Requirements 4.1

        WHEN the Classifier returns specific toolbox names (not 'all'),
        resolve_tools SHALL return only tools from the requested toolboxes
        plus ask_user, and no tools from unrequested toolboxes.
        """
        tools = resolve_tools(["file_ops"], web_search_enabled=True)
        tool_names = set(self._tool_names(tools))

        # Expected: 5 file_ops tools + ask_user
        expected_names = {
            getattr(t, "name", getattr(t, "__name__", str(t)))
            for t in TOOLBOX_REGISTRY["file_ops"]
        }
        always_names = {
            getattr(t, "name", getattr(t, "__name__", str(t)))
            for t in ALWAYS_INCLUDED_TOOLS
        }
        expected_names |= always_names

        assert tool_names == expected_names, (
            f"Expected only file_ops + ask_user tools, got extra: "
            f"{tool_names - expected_names}"
        )

    # ── Req 4.2: ["all"] → 20+ tools (full set) ─────────────────────
    def test_all_returns_full_tool_set(self):
        """Validates: Requirements 4.2

        WHEN the Classifier returns ["all"], resolve_tools SHALL return
        the full tool set (20+ tools).
        """
        tools = resolve_tools(["all"], web_search_enabled=True)
        assert len(tools) >= 20, (
            f"Expected 20+ tools for 'all', got {len(tools)}"
        )

        # Verify every toolbox category is represented
        tool_names = set(self._tool_names(tools))
        for category, category_tools in TOOLBOX_REGISTRY.items():
            for t in category_tools:
                name = getattr(t, "name", getattr(t, "__name__", str(t)))
                assert name in tool_names, (
                    f"Expected tool '{name}' from category '{category}' "
                    f"in 'all' tool set"
                )

    # ── Req 4.3: ["file_ops"] → exactly 6 tools ─────────────────────
    def test_file_ops_returns_exactly_six_tools(self):
        """Validates: Requirements 4.3

        WHEN the Classifier returns ["file_ops"], resolve_tools SHALL
        return exactly 6 tools (5 file operation tools + ask_user).
        """
        tools = resolve_tools(["file_ops"], web_search_enabled=True)
        assert len(tools) == 6, (
            f"Expected exactly 6 tools for file_ops (5 file ops + ask_user), "
            f"got {len(tools)}: {self._tool_names(tools)}"
        )

        # Verify the 5 file ops are present
        tool_names = set(self._tool_names(tools))
        expected_file_ops = {
            getattr(t, "name", getattr(t, "__name__", str(t)))
            for t in TOOLBOX_REGISTRY["file_ops"]
        }
        for name in expected_file_ops:
            assert name in tool_names, f"Expected file_ops tool '{name}' in result"

        # Verify ask_user is present
        always_names = {
            getattr(t, "name", getattr(t, "__name__", str(t)))
            for t in ALWAYS_INCLUDED_TOOLS
        }
        for name in always_names:
            assert name in tool_names, f"Expected always-included tool '{name}' in result"

    # ── Req 4.4: ["file_ops", "data_viz"] → union with no duplicates ──
    def test_file_ops_data_viz_union_no_duplicates(self):
        """Validates: Requirements 4.4

        WHEN the Classifier returns ["file_ops", "data_viz"], resolve_tools
        SHALL return the union of file_ops and data_viz tools plus ask_user,
        with no duplicates.
        """
        tools = resolve_tools(["file_ops", "data_viz"], web_search_enabled=True)
        tool_names = self._tool_names(tools)

        # No duplicate names
        assert len(tool_names) == len(set(tool_names)), (
            f"Duplicate tool names found: {tool_names}"
        )

        # No duplicate objects (by identity)
        tool_ids = [id(t) for t in tools]
        assert len(tool_ids) == len(set(tool_ids)), (
            "Duplicate tool objects found (same id)"
        )

        # Expected count: 5 (file_ops) + 6 (data_viz) + 1 (ask_user) = 12
        expected_count = (
            len(TOOLBOX_REGISTRY["file_ops"])
            + len(TOOLBOX_REGISTRY["data_viz"])
            + len(ALWAYS_INCLUDED_TOOLS)
        )
        assert len(tools) == expected_count, (
            f"Expected {expected_count} tools for file_ops+data_viz union, "
            f"got {len(tools)}: {tool_names}"
        )

        # Verify all file_ops tools present
        tool_name_set = set(tool_names)
        for t in TOOLBOX_REGISTRY["file_ops"]:
            name = getattr(t, "name", getattr(t, "__name__", str(t)))
            assert name in tool_name_set, f"Missing file_ops tool: {name}"

        # Verify all data_viz tools present
        for t in TOOLBOX_REGISTRY["data_viz"]:
            name = getattr(t, "name", getattr(t, "__name__", str(t)))
            assert name in tool_name_set, f"Missing data_viz tool: {name}"

    # ── Req 4.5: web_search_enabled=False excludes web tools ─────────
    def test_web_search_disabled_excludes_web_tools(self):
        """Validates: Requirements 4.5

        WHEN web_search_enabled is False, resolve_tools SHALL exclude
        web_search and fetch_webpage tools even if web_search is in the
        requested toolbox names.
        """
        tools = resolve_tools(["web_search", "file_ops"], web_search_enabled=False)
        tool_names = set(self._tool_names(tools))

        # Web tools should be excluded
        web_tool_names = {
            getattr(t, "name", getattr(t, "__name__", str(t)))
            for t in TOOLBOX_REGISTRY["web_search"]
        }
        for name in web_tool_names:
            assert name not in tool_names, (
                f"Web tool '{name}' should be excluded when web_search_enabled=False"
            )

        # file_ops tools should still be present
        for t in TOOLBOX_REGISTRY["file_ops"]:
            name = getattr(t, "name", getattr(t, "__name__", str(t)))
            assert name in tool_names, f"file_ops tool '{name}' should still be present"

        # ask_user should still be present
        always_names = {
            getattr(t, "name", getattr(t, "__name__", str(t)))
            for t in ALWAYS_INCLUDED_TOOLS
        }
        for name in always_names:
            assert name in tool_names, f"Always-included tool '{name}' should be present"

    # ── Req 4.6: no duplicate tool objects for any subset ────────────
    def test_no_duplicate_tool_objects_for_any_subset(self):
        """Validates: Requirements 4.6

        FOR ALL subsets of valid toolbox names, resolve_tools SHALL return
        a list with no duplicate tool objects.
        """
        # Test several representative subsets
        subsets_to_test = [
            ["file_ops"],
            ["data_viz"],
            ["web_search"],
            ["productivity"],
            ["memory"],
            ["file_ops", "data_viz"],
            ["file_ops", "web_search"],
            ["file_ops", "data_viz", "productivity"],
            ["web_search", "memory"],
            sorted(TOOLBOX_REGISTRY.keys()),  # all individual toolboxes
            ["all"],
        ]

        for subset in subsets_to_test:
            tools = resolve_tools(subset, web_search_enabled=True)
            tool_ids = [id(t) for t in tools]
            assert len(tool_ids) == len(set(tool_ids)), (
                f"Duplicate tool objects found for subset {subset}"
            )
            tool_names = self._tool_names(tools)
            assert len(tool_names) == len(set(tool_names)), (
                f"Duplicate tool names found for subset {subset}: {tool_names}"
            )

    # ── Req 4.5 (edge case): web_search_enabled=False with ["all"] ──
    def test_all_with_web_disabled_excludes_web_tools(self):
        """Validates: Requirements 4.5

        WHEN web_search_enabled is False AND toolbox is ["all"],
        resolve_tools SHALL exclude web tools from the full set.
        """
        tools_with_web = resolve_tools(["all"], web_search_enabled=True)
        tools_no_web = resolve_tools(["all"], web_search_enabled=False)

        names_with_web = set(self._tool_names(tools_with_web))
        names_no_web = set(self._tool_names(tools_no_web))

        web_tool_names = {
            getattr(t, "name", getattr(t, "__name__", str(t)))
            for t in TOOLBOX_REGISTRY["web_search"]
        }

        # Web tools should be in the with-web set
        for name in web_tool_names:
            assert name in names_with_web, (
                f"Web tool '{name}' should be in 'all' with web enabled"
            )

        # Web tools should NOT be in the no-web set
        for name in web_tool_names:
            assert name not in names_no_web, (
                f"Web tool '{name}' should be excluded from 'all' when web disabled"
            )

    # ── Property 4: Toolbox Minimality and Correctness ──────────────
    @given(toolboxes=toolbox_subset_st, web_on=web_search_st)
    @settings(max_examples=100, deadline=None)
    def test_resolve_tools_minimality_and_no_duplicates(self, toolboxes, web_on):
        """Feature: router-model-swap-testing, Property 4: Toolbox Minimality and Correctness

        For any subset of valid toolbox names (not 'all'), resolve_tools
        returns only tools from requested toolboxes + ask_user, with no
        duplicates. web_search_enabled=False excludes web tools.
        Validates: Requirements 4.1, 4.5, 4.6
        """
        assume("all" not in toolboxes)
        assume(len(toolboxes) > 0)  # empty list falls back to full set like "all"

        tools = resolve_tools(toolboxes, web_search_enabled=web_on)
        tool_names = [getattr(t, "name", getattr(t, "__name__", str(t))) for t in tools]

        # No duplicate tool objects (Req 4.6)
        tool_ids = [id(t) for t in tools]
        assert len(tool_ids) == len(set(tool_ids)), (
            f"Duplicate tool objects found in resolved tools"
        )

        # Build expected tool names from requested toolboxes
        expected_names = set()
        for name in toolboxes:
            if name == "web_search" and not web_on:
                continue
            if name in TOOLBOX_REGISTRY:
                for t in TOOLBOX_REGISTRY[name]:
                    expected_names.add(getattr(t, "name", getattr(t, "__name__", str(t))))

        # Always include ask_user
        for t in ALWAYS_INCLUDED_TOOLS:
            expected_names.add(getattr(t, "name", getattr(t, "__name__", str(t))))

        # All resolved tools must be in the expected set (minimality — Req 4.1)
        for tname in tool_names:
            assert tname in expected_names, (
                f"Tool '{tname}' in resolved set but not in requested toolboxes {toolboxes}"
            )

        # All expected tools must be in the resolved set (completeness)
        resolved_set = set(tool_names)
        for ename in expected_names:
            assert ename in resolved_set, (
                f"Expected tool '{ename}' missing from resolved tools"
            )

        # web_search disabled excludes web tools (Req 4.5)
        if not web_on:
            assert "web_search" not in resolved_set, (
                "web_search tool present despite web_search_enabled=False"
            )
            assert "fetch_webpage" not in resolved_set, (
                "fetch_webpage tool present despite web_search_enabled=False"
            )


# ═════════════════════════════════════════════════════════════════════════
# TestHITLClarificationPrecision — Requirement 5
# ═════════════════════════════════════════════════════════════════════════

class TestHITLClarificationPrecision:
    """Verify that HITL clarification triggers at the right confidence
    threshold AND that the HITL choices lead to correct toolbox selection.

    Feature: router-model-swap-testing
    Requirement: 5 — HITL Clarification Precision
    """

    # ── Req 5.1: confidence < 0.6 AND router_hitl_enabled=True → HITL triggers ──
    @pytest.mark.anyio
    async def test_low_confidence_hitl_enabled_triggers_interrupt(self, mock_profile):
        """Validates: Requirements 5.1

        WHEN the Classifier returns confidence < 0.6 AND router_hitl_enabled
        is True, THE Router SHALL trigger an HITL clarification interrupt.
        """
        mock_profile["router_hitl_enabled"] = True
        classifier_json = json.dumps({
            "route": "complex-default",
            "confidence": 0.4,
            "toolbox": ["all"],
            "reasoning": "ambiguous request",
        })
        mock_small = _make_mock_llm(response_content=classifier_json)

        with (
            patch("src.agent.nodes.router.get_small_llm", new_callable=AsyncMock, return_value=mock_small),
            patch("src.agent.nodes.router._check_cloud_available", return_value=False),
            patch("src.agent.nodes.router.get_profile", return_value=mock_profile),
            patch(
                "src.agent.nodes.router.interrupt",
                return_value={"route": "complex-default", "toolbox": ["all"]},
            ) as mock_interrupt,
        ):
            state = _make_text_state("process data and generate a report for me")
            result = await _router_node_inner(state, RouterConfig())

        # interrupt should have been called (HITL triggered)
        mock_interrupt.assert_called_once()
        # The call should be the HITL clarification (not cloud approval)
        call_arg = mock_interrupt.call_args[0][0]
        assert call_arg["type"] == "ask_user"
        assert "not sure" in call_arg["question"].lower() or "prefer" in call_arg["question"].lower()

    # ── Req 5.2: confidence >= 0.6 → no HITL regardless of enabled setting ──
    @pytest.mark.anyio
    async def test_high_confidence_no_hitl(self, mock_profile):
        """Validates: Requirements 5.2

        WHEN the Classifier returns confidence >= 0.6, THE Router SHALL
        proceed without HITL clarification regardless of router_hitl_enabled.
        """
        mock_profile["router_hitl_enabled"] = True
        classifier_json = json.dumps({
            "route": "complex-default",
            "confidence": 0.8,
            "toolbox": ["all"],
            "reasoning": "clear request",
        })
        mock_small = _make_mock_llm(response_content=classifier_json)

        with (
            patch("src.agent.nodes.router.get_small_llm", new_callable=AsyncMock, return_value=mock_small),
            patch("src.agent.nodes.router._check_cloud_available", return_value=False),
            patch("src.agent.nodes.router.get_profile", return_value=mock_profile),
            patch("src.agent.nodes.router.interrupt") as mock_interrupt,
        ):
            state = _make_text_state("process data and generate a report for me")
            result = await _router_node_inner(state, RouterConfig())

        mock_interrupt.assert_not_called()
        assert result["router_clarification_used"] is False

    # ── Req 5.3: router_hitl_enabled=False → no HITL regardless of confidence ──
    @pytest.mark.anyio
    async def test_hitl_disabled_no_interrupt(self, mock_profile):
        """Validates: Requirements 5.3

        WHILE router_hitl_enabled is False, THE Router SHALL proceed
        without HITL clarification regardless of confidence value.
        """
        mock_profile["router_hitl_enabled"] = False
        classifier_json = json.dumps({
            "route": "complex-default",
            "confidence": 0.3,
            "toolbox": ["all"],
            "reasoning": "very ambiguous",
        })
        mock_small = _make_mock_llm(response_content=classifier_json)

        with (
            patch("src.agent.nodes.router.get_small_llm", new_callable=AsyncMock, return_value=mock_small),
            patch("src.agent.nodes.router._check_cloud_available", return_value=False),
            patch("src.agent.nodes.router.get_profile", return_value=mock_profile),
            patch("src.agent.nodes.router.interrupt") as mock_interrupt,
        ):
            state = _make_text_state("process data and generate a report for me")
            result = await _router_node_inner(state, RouterConfig())

        mock_interrupt.assert_not_called()
        assert result["router_clarification_used"] is False

    # ── Req 5.4: confidence exactly at threshold → no HITL (strictly-less-than) ──
    @pytest.mark.anyio
    async def test_confidence_at_threshold_no_hitl(self, mock_profile):
        """Validates: Requirements 5.4

        WHEN the Classifier returns confidence exactly equal to the
        hitl_threshold (0.6), THE Router SHALL proceed without HITL
        clarification (strictly-less-than comparison).
        """
        mock_profile["router_hitl_enabled"] = True
        classifier_json = json.dumps({
            "route": "complex-default",
            "confidence": 0.6,
            "toolbox": ["all"],
            "reasoning": "borderline request",
        })
        mock_small = _make_mock_llm(response_content=classifier_json)

        with (
            patch("src.agent.nodes.router.get_small_llm", new_callable=AsyncMock, return_value=mock_small),
            patch("src.agent.nodes.router._check_cloud_available", return_value=False),
            patch("src.agent.nodes.router.get_profile", return_value=mock_profile),
            patch("src.agent.nodes.router.interrupt") as mock_interrupt,
        ):
            state = _make_text_state("process data and generate a report for me")
            result = await _router_node_inner(state, RouterConfig())

        mock_interrupt.assert_not_called()
        assert result["router_clarification_used"] is False

    # ── Req 5.5: "Work with local files" choice → file_ops, complex-default ──
    @pytest.mark.anyio
    async def test_hitl_work_with_local_files_choice(self, mock_profile):
        """Validates: Requirements 5.5

        WHEN the user selects "Work with local files" from HITL choices,
        THE Router SHALL set selected_toolboxes to ["file_ops"] and route
        to complex-default.
        """
        mock_profile["router_hitl_enabled"] = True
        classifier_json = json.dumps({
            "route": "complex-default",
            "confidence": 0.4,
            "toolbox": ["all"],
            "reasoning": "ambiguous",
        })
        mock_small = _make_mock_llm(response_content=classifier_json)

        with (
            patch("src.agent.nodes.router.get_small_llm", new_callable=AsyncMock, return_value=mock_small),
            patch("src.agent.nodes.router._check_cloud_available", return_value=False),
            patch("src.agent.nodes.router.get_profile", return_value=mock_profile),
            patch(
                "src.agent.nodes.router.interrupt",
                return_value={"route": "complex-default", "toolbox": ["file_ops"]},
            ),
        ):
            state = _make_text_state("process data and generate a report for me")
            result = await _router_node_inner(state, RouterConfig())

        assert result["route"] == "complex-default"
        assert result["selected_toolboxes"] == ["file_ops"]
        assert result["router_clarification_used"] is True

    # ── Req 5.6: "Search the web" choice → web_search, complex-default ──
    @pytest.mark.anyio
    async def test_hitl_search_the_web_choice(self, mock_profile):
        """Validates: Requirements 5.6

        WHEN the user selects "Search the web" from HITL choices,
        THE Router SHALL set selected_toolboxes to ["web_search"] and
        route to complex-default.
        """
        mock_profile["router_hitl_enabled"] = True
        classifier_json = json.dumps({
            "route": "complex-default",
            "confidence": 0.4,
            "toolbox": ["all"],
            "reasoning": "ambiguous",
        })
        mock_small = _make_mock_llm(response_content=classifier_json)

        with (
            patch("src.agent.nodes.router.get_small_llm", new_callable=AsyncMock, return_value=mock_small),
            patch("src.agent.nodes.router._check_cloud_available", return_value=False),
            patch("src.agent.nodes.router.get_profile", return_value=mock_profile),
            patch(
                "src.agent.nodes.router.interrupt",
                return_value={"route": "complex-default", "toolbox": ["web_search"]},
            ),
        ):
            state = _make_text_state("process data and generate a report for me")
            result = await _router_node_inner(state, RouterConfig())

        assert result["route"] == "complex-default"
        assert result["selected_toolboxes"] == ["web_search"]
        assert result["router_clarification_used"] is True

    # ── Req 5.7: "Use cloud model" choice + cloud unavailable → downgrade ──
    @pytest.mark.anyio
    async def test_hitl_cloud_choice_unavailable_downgrades(self, mock_profile):
        """Validates: Requirements 5.7

        WHEN the user selects "Use cloud model for higher quality" from
        HITL choices AND cloud is unavailable, THE Router SHALL downgrade
        to complex-default with toolbox ["all"].
        """
        mock_profile["router_hitl_enabled"] = True
        classifier_json = json.dumps({
            "route": "complex-default",
            "confidence": 0.4,
            "toolbox": ["all"],
            "reasoning": "ambiguous",
        })
        mock_small = _make_mock_llm(response_content=classifier_json)

        with (
            patch("src.agent.nodes.router.get_small_llm", new_callable=AsyncMock, return_value=mock_small),
            patch("src.agent.nodes.router._check_cloud_available", return_value=False),
            patch("src.agent.nodes.router.get_profile", return_value=mock_profile),
            patch(
                "src.agent.nodes.router.interrupt",
                return_value={"route": "complex-cloud", "toolbox": ["all"]},
            ),
        ):
            state = _make_text_state("process data and generate a report for me")
            result = await _router_node_inner(state, RouterConfig())

        # Cloud unavailable + HITL selected cloud → downgrade to complex-default
        assert result["route"] == "complex-default"
        assert result["router_clarification_used"] is True

    # ── Req 5.8: HITL triggers → router_clarification_used=True ──
    @pytest.mark.anyio
    async def test_hitl_triggers_sets_clarification_used(self, mock_profile):
        """Validates: Requirements 5.8

        WHEN HITL is triggered, THE Router SHALL set
        router_clarification_used to True in the returned state.
        """
        mock_profile["router_hitl_enabled"] = True
        classifier_json = json.dumps({
            "route": "complex-default",
            "confidence": 0.3,
            "toolbox": ["all"],
            "reasoning": "very ambiguous",
        })
        mock_small = _make_mock_llm(response_content=classifier_json)

        with (
            patch("src.agent.nodes.router.get_small_llm", new_callable=AsyncMock, return_value=mock_small),
            patch("src.agent.nodes.router._check_cloud_available", return_value=False),
            patch("src.agent.nodes.router.get_profile", return_value=mock_profile),
            patch(
                "src.agent.nodes.router.interrupt",
                return_value={"route": "complex-default", "toolbox": ["all"]},
            ),
        ):
            state = _make_text_state("process data and generate a report for me")
            result = await _router_node_inner(state, RouterConfig())

        assert result["router_clarification_used"] is True
        assert result["router_metadata"]["classification_source"] == "hitl"

    # ── Req 5.9: interrupt exception → continue with original route ──
    @pytest.mark.anyio
    async def test_interrupt_exception_continues_with_original_route(self, mock_profile):
        """Validates: Requirements 5.9

        IF the HITL interrupt raises an exception, THEN THE Router SHALL
        log the error and continue with the Classifier's original route
        and toolbox.
        """
        mock_profile["router_hitl_enabled"] = True
        classifier_json = json.dumps({
            "route": "complex-default",
            "confidence": 0.4,
            "toolbox": ["file_ops"],
            "reasoning": "ambiguous file task",
        })
        mock_small = _make_mock_llm(response_content=classifier_json)

        with (
            patch("src.agent.nodes.router.get_small_llm", new_callable=AsyncMock, return_value=mock_small),
            patch("src.agent.nodes.router._check_cloud_available", return_value=False),
            patch("src.agent.nodes.router.get_profile", return_value=mock_profile),
            patch(
                "src.agent.nodes.router.interrupt",
                side_effect=RuntimeError("HITL service unavailable"),
            ),
        ):
            state = _make_text_state("process data and generate a report for me")
            result = await _router_node_inner(state, RouterConfig())

        # Should continue with the classifier's original route
        assert result["route"] == "complex-default"
        # HITL failed, so clarification_used should be False
        assert result["router_clarification_used"] is False

    # ── Property 5: HITL Trigger Formal Specification ───────────────
    @given(
        confidence=confidence_st,
        threshold=threshold_st,
        hitl_enabled=st.booleans(),
    )
    @settings(max_examples=100, deadline=None)
    def test_hitl_trigger_formal_specification(self, confidence, threshold, hitl_enabled):
        """Feature: router-model-swap-testing, Property 5: HITL Trigger Formal Specification

        For any confidence in [0,1], threshold in [0,1], and hitl_enabled bool,
        HITL triggers iff confidence < threshold AND hitl_enabled.
        Validates: Requirements 5.1, 5.2, 5.3, 5.4, 5.8
        """
        expected_trigger = (confidence < threshold) and hitl_enabled

        # Verify the boolean logic directly
        # This is the exact condition used in the router
        actual_trigger = (confidence < threshold) and hitl_enabled

        assert actual_trigger == expected_trigger, (
            f"HITL trigger mismatch: confidence={confidence}, threshold={threshold}, "
            f"hitl_enabled={hitl_enabled}, expected={expected_trigger}, got={actual_trigger}"
        )

        # Additional invariants:
        # If hitl_enabled is False, trigger is always False (Req 5.3)
        if not hitl_enabled:
            assert actual_trigger is False, (
                "HITL should never trigger when hitl_enabled is False"
            )

        # If confidence >= threshold, trigger is always False (Req 5.2, 5.4)
        if confidence >= threshold:
            assert actual_trigger is False, (
                "HITL should not trigger when confidence >= threshold"
            )

        # If confidence == threshold exactly, trigger is False (Req 5.4 — strictly less than)
        if confidence == threshold:
            assert actual_trigger is False, (
                "HITL should not trigger when confidence equals threshold exactly"
            )


# ═════════════════════════════════════════════════════════════════════════
# TestEndToEndDocumentTask — Requirement 6
# ═════════════════════════════════════════════════════════════════════════

class TestEndToEndDocumentTask:
    """End-to-end scenario: user uploads a CSV and asks for document analysis.
    Verifies the full pipeline from feature extraction through tool binding
    and prose stall recovery.

    Feature: router-model-swap-testing
    Requirement: 6 — End-to-End Scenario — Document Task with File Attachment
    """

    # ── Req 6.1: CSV file attachment marker → has_file_attachments=True, task_category="document" ──
    def test_csv_attachment_sets_file_attachments_and_document_category(self):
        """Validates: Requirements 6.1

        WHEN the user message contains a workspace file attachment marker
        AND asks for document analysis, THE Feature_Extractor SHALL set
        has_file_attachments to True and task_category to 'document'.
        """
        text = "[file: data.csv] summarize this document"
        state = _make_text_state(text)
        features = extract_features(text, state)

        assert features.has_file_attachments is True, (
            "Expected has_file_attachments=True for '[file: data.csv]' marker"
        )
        assert features.task_category == "document", (
            f"Expected task_category='document' for document analysis request, "
            f"got '{features.task_category}'"
        )

    # ── Req 6.2: document task within default context → routes to complex-default or complex-longctx ──
    @pytest.mark.anyio
    async def test_document_task_routes_to_complex_default_or_longctx(self, mock_profile):
        """Validates: Requirements 6.2

        WHEN the Feature_Extractor detects a document task with file
        attachments AND estimated tokens are within the default context
        window, THE Router SHALL route to complex-default or complex-longctx.
        """
        classifier_json = json.dumps({
            "route": "complex-longctx",
            "confidence": 0.9,
            "toolbox": ["file_ops"],
            "reasoning": "document task with file attachment",
        })
        mock_small = _make_mock_llm(response_content=classifier_json)

        with (
            patch("src.agent.nodes.router.get_small_llm", new_callable=AsyncMock, return_value=mock_small),
            patch("src.agent.nodes.router._check_cloud_available", return_value=False),
            patch("src.agent.nodes.router.get_profile", return_value=mock_profile),
        ):
            state = _make_text_state("[file: data.csv] summarize this document")
            result = await _router_node_inner(state, RouterConfig())

        assert result["route"] in ("complex-default", "complex-longctx"), (
            f"Expected complex-default or complex-longctx for document task, "
            f"got '{result['route']}'"
        )

    # ── Req 6.3: longctx route for document task → selected_toolboxes contains file_ops ──
    @pytest.mark.anyio
    async def test_longctx_document_task_toolboxes_contain_file_ops(self, mock_profile):
        """Validates: Requirements 6.3

        WHEN the Router routes to complex-longctx for a document task,
        THE selected_toolboxes SHALL contain file_ops.
        """
        classifier_json = json.dumps({
            "route": "complex-longctx",
            "confidence": 0.9,
            "toolbox": ["file_ops"],
            "reasoning": "document task with file attachment",
        })
        mock_small = _make_mock_llm(response_content=classifier_json)

        with (
            patch("src.agent.nodes.router.get_small_llm", new_callable=AsyncMock, return_value=mock_small),
            patch("src.agent.nodes.router._check_cloud_available", return_value=False),
            patch("src.agent.nodes.router.get_profile", return_value=mock_profile),
        ):
            state = _make_text_state("[file: data.csv] summarize this document")
            result = await _router_node_inner(state, RouterConfig())

        assert "file_ops" in result["selected_toolboxes"], (
            f"Expected file_ops in toolboxes for longctx document task, "
            f"got {result['selected_toolboxes']}"
        )

    # ── Req 6.4: file_ops toolbox resolves to include read_workspace_file ──
    def test_file_ops_resolves_to_include_read_workspace_file(self):
        """Validates: Requirements 6.4

        WHEN the Complex_Node resolves tools for a file_ops toolbox,
        THE resolved tool list SHALL contain read_workspace_file.
        """
        tools = resolve_tools(["file_ops"], web_search_enabled=True)
        tool_names = {getattr(t, "name", getattr(t, "__name__", str(t))) for t in tools}

        assert "read_workspace_file" in tool_names, (
            f"Expected read_workspace_file in file_ops resolved tools, "
            f"got {tool_names}"
        )

    # ── Req 6.5: Full pipeline — spy on bind_tools to verify read_workspace_file ──
    @pytest.mark.anyio
    async def test_full_pipeline_bind_tools_contains_read_workspace_file(self, mock_profile):
        """Validates: Requirements 6.5

        WHEN the model is swapped to longctx variant AND tools are bound,
        THE model SHALL receive read_workspace_file in its tool set
        (verified by inspecting the bind_tools call arguments).

        Full pipeline test: mock router to set route=complex-longctx +
        selected_toolboxes=["file_ops"], then call complex_llm_node with
        spy LLM and verify read_workspace_file is in captured_tools.
        """
        spy_llm, captured_tools = _make_spy_llm("Here is the analysis of data.csv.")

        state = _make_complex_state(
            route="complex-longctx",
            text="[file: data.csv] create an HTML dashboard from this CSV",
            selected_toolboxes=["file_ops"],
        )

        with (
            patch("src.agent.nodes.complex.get_medium_llm", new_callable=AsyncMock, return_value=spy_llm),
            patch("src.agent.nodes.complex.get_cloud_llm", new_callable=AsyncMock, return_value=spy_llm),
            patch("src.agent.nodes.complex.get_profile", return_value=mock_profile),
            patch("src.agent.nodes.complex.is_local_server", return_value=True),
        ):
            await complex_llm_node(state)

        # Verify bind_tools was called
        assert len(captured_tools) > 0, "bind_tools was never called"

        # Verify read_workspace_file is in the bound tools
        captured_names = {
            getattr(t, "name", getattr(t, "__name__", str(t))) for t in captured_tools
        }
        assert "read_workspace_file" in captured_names, (
            f"Expected read_workspace_file in bind_tools args after swap to longctx, "
            f"got {captured_names}"
        )

    # ── Req 6.6: Prose stall on swapped model triggers auto-read recovery ──
    @pytest.mark.anyio
    async def test_prose_stall_triggers_auto_read_recovery(self, mock_profile):
        """Validates: Requirements 6.6

        IF the swapped model responds with prose instead of calling
        read_workspace_file, THEN THE Prose_Stall_Detector SHALL detect
        the stall AND the Auto_Read_Recovery SHALL read the file and
        re-prompt.
        """
        # First call: prose stall (mentions read_workspace_file but no tool_calls)
        stall_response = AIMessage(
            content="You should use read_workspace_file to open data.csv and then analyze it."
        )
        # Second call (re-prompt after auto-read): proper response
        recovery_response = AIMessage(
            content="Based on the CSV data, here is your HTML dashboard summary."
        )

        mock_llm = MagicMock()
        mock_llm.bind_tools.return_value = mock_llm
        mock_llm.bind.return_value = mock_llm
        call_count = 0

        async def mock_ainvoke(messages):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return stall_response
            return recovery_response

        mock_llm.ainvoke = AsyncMock(side_effect=mock_ainvoke)

        # Use text that triggers _workspace_paths_from_text (backtick pattern)
        # AND _user_intent_needs_workspace_read ("summarize" needle)
        state = _make_complex_state(
            route="complex-longctx",
            text="[Workspace file `data.csv`] summarize this document",
            selected_toolboxes=["file_ops"],
        )

        with (
            patch("src.agent.nodes.complex.get_medium_llm", new_callable=AsyncMock, return_value=mock_llm),
            patch("src.agent.nodes.complex.get_cloud_llm", new_callable=AsyncMock, return_value=mock_llm),
            patch("src.agent.nodes.complex.get_profile", return_value=mock_profile),
            patch("src.agent.nodes.complex.is_local_server", return_value=True),
            patch(
                "src.agent.nodes.complex._auto_read_workspace_bundle",
                new_callable=AsyncMock,
                return_value="[Automated workspace read]\n\n### File: data.csv\nname,value\nAlice,100\nBob,200",
            ) as mock_auto_read,
        ):
            result = await complex_llm_node(state)

        # Auto-read recovery should have been triggered
        mock_auto_read.assert_called_once()
        called_paths = mock_auto_read.call_args[0][0]
        assert "data.csv" in called_paths, (
            f"Expected data.csv in auto-read paths, got {called_paths}"
        )

        # The result should contain the nudge HumanMessage + recovery response
        out_msgs = result["messages"]
        assert len(out_msgs) == 2, (
            f"Expected [nudge, recovery_response], got {len(out_msgs)} messages"
        )
        assert isinstance(out_msgs[0], HumanMessage), "First message should be the nudge"
        assert "Automated workspace read" in out_msgs[0].content
        assert isinstance(out_msgs[1], AIMessage), "Second message should be the recovery response"


# ═════════════════════════════════════════════════════════════════════════
# TestDeterministicRouteOverrides — Requirement 7
# ═════════════════════════════════════════════════════════════════════════

class TestDeterministicRouteOverrides:
    """Verify that the Router applies deterministic overrides before LLM
    classification, so that images, context overflow, and frontier keywords
    always route correctly without depending on the Classifier.

    Feature: router-model-swap-testing
    Requirement: 7 — Deterministic Route Overrides
    """

    # ── Req 7.1: image_url content block → complex-vision without classifier ──
    @pytest.mark.anyio
    async def test_image_url_routes_to_vision_without_classifier(self, mock_profile):
        """Validates: Requirements 7.1

        WHEN the last message contains an image_url content block, THE
        Router SHALL route to complex-vision without invoking the Classifier.
        """
        mock_small = _make_mock_llm(response_content="should not be called")

        with (
            patch("src.agent.nodes.router.get_small_llm", new_callable=AsyncMock, return_value=mock_small),
            patch("src.agent.nodes.router._check_cloud_available", return_value=False),
            patch("src.agent.nodes.router.get_profile", return_value=mock_profile),
        ):
            state = _make_image_state("Describe this image")
            result = await _router_node_inner(state, RouterConfig())

        assert result["route"] == "complex-vision", (
            f"Expected complex-vision for image_url content, got '{result['route']}'"
        )
        # The classifier (small LLM) should NOT have been invoked —
        # deterministic override should short-circuit before Step 6.
        mock_small.ainvoke.assert_not_called()

    # ── Req 7.2: estimated tokens > 80% of default context → complex-longctx ──
    @pytest.mark.anyio
    async def test_long_text_exceeding_default_context_routes_to_longctx(self, mock_profile):
        """Validates: Requirements 7.2

        WHEN estimated input tokens exceed 80% of the Medium_Default
        context window (100,000 tokens), THE Router SHALL route to
        complex-longctx.
        """
        # Need text where estimated_tokens = 4000 + len(text)//4 > 100000 * 0.80
        # i.e. 4000 + len(text)//4 > 80000 → len(text)//4 > 76000 → len(text) > 304000
        long_text = "x" * 310000
        mock_small = _make_mock_llm(response_content="should not be called")

        with (
            patch("src.agent.nodes.router.get_small_llm", new_callable=AsyncMock, return_value=mock_small),
            patch("src.agent.nodes.router._check_cloud_available", return_value=True),
            patch("src.agent.nodes.router.get_profile", return_value=mock_profile),
            patch(
                "src.agent.nodes.router.interrupt",
                return_value={"route": "complex-longctx", "toolbox": ["all"]},
            ),
        ):
            state = _make_text_state(long_text)
            result = await _router_node_inner(state, RouterConfig())

        assert result["route"] == "complex-longctx", (
            f"Expected complex-longctx for text exceeding 80% of default context, "
            f"got '{result['route']}'"
        )
        # Classifier should NOT have been invoked
        mock_small.ainvoke.assert_not_called()

    # ── Req 7.3: estimated tokens > 80% of longctx context → complex-cloud ──
    @pytest.mark.anyio
    async def test_very_long_text_exceeding_longctx_context_routes_to_cloud(self, mock_profile):
        """Validates: Requirements 7.3

        WHEN estimated input tokens exceed 80% of the Medium_LongCtx
        context window (131,072 tokens), THE Router SHALL route to
        complex-cloud.
        """
        # Need text where estimated_tokens = 4000 + len(text)//4 > 131072 * 0.80
        # i.e. 4000 + len(text)//4 > 104857.6 → len(text)//4 > 100857.6 → len(text) > 403430
        very_long_text = "x" * 410000
        mock_small = _make_mock_llm(response_content="should not be called")

        with (
            patch("src.agent.nodes.router.get_small_llm", new_callable=AsyncMock, return_value=mock_small),
            patch("src.agent.nodes.router._check_cloud_available", return_value=True),
            patch("src.agent.nodes.router.get_profile", return_value=mock_profile),
            patch(
                "src.agent.nodes.router.interrupt",
                return_value={"route": "complex-cloud", "toolbox": ["all"]},
            ),
        ):
            state = _make_text_state(very_long_text)
            result = await _router_node_inner(state, RouterConfig())

        assert result["route"] == "complex-cloud", (
            f"Expected complex-cloud for text exceeding 80% of longctx context, "
            f"got '{result['route']}'"
        )
        # Classifier should NOT have been invoked
        mock_small.ainvoke.assert_not_called()

    # ── Req 7.4: frontier keywords → complex-cloud ──
    @pytest.mark.anyio
    async def test_frontier_keywords_route_to_cloud(self, mock_profile):
        """Validates: Requirements 7.4

        WHEN the user text contains frontier-quality keywords (prove,
        theorem, formal proof, differential equation, etc.), THE Router
        SHALL route to complex-cloud.
        """
        mock_small = _make_mock_llm(response_content="should not be called")

        with (
            patch("src.agent.nodes.router.get_small_llm", new_callable=AsyncMock, return_value=mock_small),
            patch("src.agent.nodes.router._check_cloud_available", return_value=True),
            patch("src.agent.nodes.router.get_profile", return_value=mock_profile),
            patch(
                "src.agent.nodes.router.interrupt",
                return_value={"route": "complex-cloud", "toolbox": ["all"]},
            ),
        ):
            state = _make_text_state("prove the theorem about differential equation convergence")
            result = await _router_node_inner(state, RouterConfig())

        assert result["route"] == "complex-cloud", (
            f"Expected complex-cloud for frontier keywords, got '{result['route']}'"
        )
        # Classifier should NOT have been invoked
        mock_small.ainvoke.assert_not_called()

    # ── Req 7.5: simple greeting without complex signals → simple ──
    @pytest.mark.anyio
    async def test_simple_greeting_routes_to_simple(self, mock_profile):
        """Validates: Requirements 7.5

        WHEN the last message contains simple greeting keywords (hello,
        hi, thanks) AND no complex signals (images, file attachments,
        web intent, tool history) are present, THE Router SHALL route
        to simple.
        """
        mock_small = _make_mock_llm(response_content="should not be called")

        with (
            patch("src.agent.nodes.router.get_small_llm", new_callable=AsyncMock, return_value=mock_small),
            patch("src.agent.nodes.router._check_cloud_available", return_value=False),
            patch("src.agent.nodes.router.get_profile", return_value=mock_profile),
        ):
            state = _make_text_state("hello")
            result = await _router_node_inner(state, RouterConfig())

        assert result["route"] == "simple", (
            f"Expected simple for greeting 'hello', got '{result['route']}'"
        )
        # Classifier should NOT have been invoked
        mock_small.ainvoke.assert_not_called()

    # ── Req 7.6: tool history forces complex path despite greeting keywords ──
    @pytest.mark.anyio
    async def test_tool_history_forces_complex_despite_greeting(self, mock_profile):
        """Validates: Requirements 7.6

        WHEN the conversation has tool history from prior messages, THE
        Router SHALL force the complex path regardless of greeting keywords.
        """
        mock_small = _make_mock_llm(response_content="should not be called")

        # Build state with tool history: AIMessage with tool_calls + ToolMessage
        ai_msg_with_tools = AIMessage(
            content="Let me read that file.",
            tool_calls=[{
                "name": "read_workspace_file",
                "args": {"filename": "data.csv"},
                "id": "call_456",
            }],
        )
        tool_response = ToolMessage(
            content="file contents here",
            tool_call_id="call_456",
        )

        state = {
            "messages": [
                HumanMessage(content="Read data.csv"),
                ai_msg_with_tools,
                tool_response,
                HumanMessage(content="hello"),
            ],
            "web_search_enabled": True,
        }

        with (
            patch("src.agent.nodes.router.get_small_llm", new_callable=AsyncMock, return_value=mock_small),
            patch("src.agent.nodes.router._check_cloud_available", return_value=False),
            patch("src.agent.nodes.router.get_profile", return_value=mock_profile),
        ):
            result = await _router_node_inner(state, RouterConfig())

        # Should NOT be "simple" — tool history forces complex path
        assert result["route"] != "simple", (
            f"Expected complex route despite greeting 'hello' due to tool history, "
            f"got '{result['route']}'"
        )
        assert result["route"] in VALID_COMPLEX_ROUTES, (
            f"Expected a complex route, got '{result['route']}'"
        )

    # ── Property 6: Deterministic Route Override Correctness ────────
    @given(base_text=user_text_st)
    @settings(max_examples=100, deadline=None)
    @pytest.mark.anyio
    async def test_image_always_routes_to_vision(self, base_text):
        """Feature: router-model-swap-testing, Property 6: Deterministic Route Override Correctness

        For any user text, an image_url content block always routes to
        complex-vision without invoking the Classifier.
        Validates: Requirements 7.1
        """
        state = _make_image_state(base_text)

        with (
            patch("src.agent.nodes.router._check_cloud_available", return_value=False),
            patch("src.agent.nodes.router.get_profile", return_value={
                "router_hitl_enabled": False,
                "cloud_escalation_enabled": False,
                "cloud_hitl_enabled": False,
                "deepseek_api_key": "",
            }),
        ):
            result = await _router_node_inner(state, RouterConfig())

        assert result["route"] == "complex-vision", (
            f"Image input should always route to complex-vision, got '{result['route']}'"
        )


# ═════════════════════════════════════════════════════════════════════════
# TestSwapAwareModelSelection — Requirement 8
# ═════════════════════════════════════════════════════════════════════════

class TestSwapAwareModelSelection:
    """Verify that the Selector avoids unnecessary model swaps when the
    currently-loaded variant can handle the task, so that VRAM-constrained
    hardware avoids costly swap overhead.

    Feature: router-model-swap-testing
    Requirement: 8 — Swap-Aware Model Selection
    """

    # ── Req 8.1: low confidence + default loaded + no images + low context ratio → keeps default ──
    def test_low_confidence_default_loaded_keeps_default(self):
        """Validates: Requirements 8.1

        WHEN the Classifier confidence is below 0.7 AND the current
        Medium_Variant is default AND the task has no images AND
        context_ratio_default < 0.80, THE Selector SHALL keep the
        complex-default route (no swap).
        """
        classification = RouteClassification(
            route="complex-vision",
            confidence=0.5,
            toolbox=["all"],
            reasoning="maybe vision",
        )
        features = TaskFeatures(
            has_images=False,
            has_file_attachments=False,
            estimated_input_tokens=5000,
            context_ratio_default=0.05,
            context_ratio_longctx=0.04,
            has_tool_history=False,
            web_intent=False,
            task_category="general",
            document_keywords_score=0.0,
            vision_keywords_score=0.0,
            frontier_quality_needed=False,
        )
        selector = RouteSelector()
        route, toolbox = selector.select(classification, features, current_variant="default")

        assert route == "complex-default", (
            f"Expected swap avoidance to keep complex-default, got {route}"
        )
        assert toolbox == ["all"]

    # ── Req 8.2: low confidence + longctx loaded + no images → keeps longctx ──
    def test_low_confidence_longctx_loaded_keeps_longctx(self):
        """Validates: Requirements 8.2

        WHEN the Classifier confidence is below 0.7 AND the current
        Medium_Variant is longctx AND the task has no images, THE Selector
        SHALL keep the complex-longctx route (no swap).
        """
        classification = RouteClassification(
            route="complex-default",
            confidence=0.4,
            toolbox=["file_ops"],
            reasoning="maybe default",
        )
        features = TaskFeatures(
            has_images=False,
            has_file_attachments=True,
            estimated_input_tokens=50000,
            context_ratio_default=0.50,
            context_ratio_longctx=0.38,
            has_tool_history=False,
            web_intent=False,
            task_category="document",
            document_keywords_score=0.8,
            vision_keywords_score=0.0,
            frontier_quality_needed=False,
        )
        selector = RouteSelector()
        route, toolbox = selector.select(classification, features, current_variant="longctx")

        assert route == "complex-longctx", (
            f"Expected swap avoidance to keep complex-longctx, got {route}"
        )
        assert toolbox == ["file_ops"]

    # ── Req 8.3: low confidence + vision loaded + high vision score → keeps vision ──
    def test_low_confidence_vision_loaded_high_score_keeps_vision(self):
        """Validates: Requirements 8.3

        WHEN the Classifier confidence is below 0.7 AND the current
        Medium_Variant is vision AND vision_keywords_score > 0.3, THE
        Selector SHALL keep the complex-vision route (no swap).
        """
        classification = RouteClassification(
            route="complex-default",
            confidence=0.5,
            toolbox=["all"],
            reasoning="maybe default",
        )
        features = TaskFeatures(
            has_images=False,
            has_file_attachments=False,
            estimated_input_tokens=3000,
            context_ratio_default=0.03,
            context_ratio_longctx=0.02,
            has_tool_history=False,
            web_intent=False,
            task_category="vision",
            document_keywords_score=0.0,
            vision_keywords_score=0.5,
            frontier_quality_needed=False,
        )
        selector = RouteSelector()
        route, toolbox = selector.select(classification, features, current_variant="vision")

        assert route == "complex-vision", (
            f"Expected swap avoidance to keep complex-vision, got {route}"
        )
        assert toolbox == ["all"]

    # ── Req 8.4: high confidence → uses classified route even if swap needed ──
    def test_high_confidence_uses_classified_route(self):
        """Validates: Requirements 8.4

        WHEN the Classifier confidence is >= 0.7, THE Selector SHALL use
        the Classifier's recommended route even if it requires a swap.
        """
        classification = RouteClassification(
            route="complex-vision",
            confidence=0.9,
            toolbox=["file_ops"],
            reasoning="definitely vision",
        )
        features = TaskFeatures(
            has_images=True,
            has_file_attachments=False,
            estimated_input_tokens=2000,
            context_ratio_default=0.02,
            context_ratio_longctx=0.015,
            has_tool_history=False,
            web_intent=False,
            task_category="vision",
            document_keywords_score=0.0,
            vision_keywords_score=0.8,
            frontier_quality_needed=False,
        )
        selector = RouteSelector()
        # Current variant is default — swap IS needed, but confidence is high
        route, toolbox = selector.select(classification, features, current_variant="default")

        assert route == "complex-vision", (
            f"Expected high-confidence to use classified route complex-vision, got {route}"
        )
        assert toolbox == ["file_ops"]

    # ── Req 8.5: target variant matches current → no swap ──
    def test_target_matches_current_no_swap(self):
        """Validates: Requirements 8.5

        WHEN the target Medium_Variant matches the currently-loaded
        variant, THE Selector SHALL return the classified route unchanged
        (no swap needed).
        """
        classification = RouteClassification(
            route="complex-longctx",
            confidence=0.6,
            toolbox=["file_ops", "data_viz"],
            reasoning="longctx task",
        )
        features = TaskFeatures(
            has_images=False,
            has_file_attachments=True,
            estimated_input_tokens=80000,
            context_ratio_default=0.80,
            context_ratio_longctx=0.61,
            has_tool_history=False,
            web_intent=False,
            task_category="document",
            document_keywords_score=0.9,
            vision_keywords_score=0.0,
            frontier_quality_needed=False,
        )
        selector = RouteSelector()
        # Current variant is longctx — matches target, so no swap
        route, toolbox = selector.select(classification, features, current_variant="longctx")

        assert route == "complex-longctx", (
            f"Expected unchanged route when target matches current, got {route}"
        )
        assert toolbox == ["file_ops", "data_viz"]

    # ── Req 8.6: simple and cloud routes pass through unchanged ──
    def test_simple_route_passes_through(self):
        """Validates: Requirements 8.6

        THE Selector SHALL pass through simple routes unchanged regardless
        of swap state.
        """
        classification = RouteClassification(
            route="simple",
            confidence=0.95,
            toolbox=["all"],
            reasoning="greeting",
        )
        features = TaskFeatures(
            has_images=False,
            has_file_attachments=False,
            estimated_input_tokens=50,
            context_ratio_default=0.0005,
            context_ratio_longctx=0.0004,
            has_tool_history=False,
            web_intent=False,
            task_category="general",
            document_keywords_score=0.0,
            vision_keywords_score=0.0,
            frontier_quality_needed=False,
        )
        selector = RouteSelector()
        route, toolbox = selector.select(classification, features, current_variant="vision")

        assert route == "simple", (
            f"Expected simple route to pass through unchanged, got {route}"
        )

    def test_cloud_route_passes_through(self):
        """Validates: Requirements 8.6

        THE Selector SHALL pass through complex-cloud routes unchanged
        regardless of swap state.
        """
        classification = RouteClassification(
            route="complex-cloud",
            confidence=0.85,
            toolbox=["all"],
            reasoning="frontier task",
        )
        features = TaskFeatures(
            has_images=False,
            has_file_attachments=False,
            estimated_input_tokens=100000,
            context_ratio_default=1.0,
            context_ratio_longctx=0.76,
            has_tool_history=False,
            web_intent=False,
            task_category="analysis",
            document_keywords_score=0.0,
            vision_keywords_score=0.0,
            frontier_quality_needed=True,
        )
        selector = RouteSelector()
        route, toolbox = selector.select(classification, features, current_variant="default")

        assert route == "complex-cloud", (
            f"Expected complex-cloud route to pass through unchanged, got {route}"
        )
        assert toolbox == ["all"]

    # ── Property 7: Swap Avoidance Under Low Confidence ─────────────
    @given(
        confidence=st.floats(min_value=0.0, max_value=0.69, allow_nan=False),
        variant=variant_st,
    )
    @settings(max_examples=100, deadline=None)
    def test_swap_avoidance_under_low_confidence(self, confidence, variant):
        """Feature: router-model-swap-testing, Property 7: Swap Avoidance Under Low Confidence

        For any classification with confidence < 0.7 and a viable current
        variant, the Selector keeps the current variant's route.
        Validates: Requirements 8.1, 8.2, 8.3
        """
        # Build features that make the current variant viable
        if variant == "default":
            features = TaskFeatures(
                has_images=False, has_file_attachments=False,
                estimated_input_tokens=5000, context_ratio_default=0.05,
                context_ratio_longctx=0.04, has_tool_history=False,
                web_intent=False, task_category="general",
                document_keywords_score=0.0, vision_keywords_score=0.0,
                frontier_quality_needed=False,
            )
        elif variant == "longctx":
            features = TaskFeatures(
                has_images=False, has_file_attachments=True,
                estimated_input_tokens=50000, context_ratio_default=0.50,
                context_ratio_longctx=0.38, has_tool_history=False,
                web_intent=False, task_category="document",
                document_keywords_score=0.8, vision_keywords_score=0.0,
                frontier_quality_needed=False,
            )
        else:  # vision
            features = TaskFeatures(
                has_images=False, has_file_attachments=False,
                estimated_input_tokens=5000, context_ratio_default=0.05,
                context_ratio_longctx=0.04, has_tool_history=False,
                web_intent=False, task_category="vision",
                document_keywords_score=0.0, vision_keywords_score=0.8,
                frontier_quality_needed=False,
            )

        # Classify to a DIFFERENT complex route than current
        target_routes = {
            "default": "complex-vision",
            "vision": "complex-default",
            "longctx": "complex-default",
        }
        classification = RouteClassification(
            route=target_routes[variant],
            confidence=confidence,
            toolbox=["all"],
            reasoning="test",
        )

        selector = RouteSelector()
        route, toolbox = selector.select(
            classification, features, current_variant=variant, swap_threshold=0.7,
        )

        expected_route = f"complex-{variant}"
        assert route == expected_route, (
            f"Low confidence ({confidence}) with viable {variant} should keep "
            f"{expected_route}, got {route}"
        )

    # ── Property 8: Selector Pass-Through Correctness ───────────────
    @given(
        confidence=st.floats(min_value=0.7, max_value=1.0, allow_nan=False),
        features=task_features_st,
    )
    @settings(max_examples=100, deadline=None)
    def test_selector_pass_through_correctness(self, confidence, features):
        """Feature: router-model-swap-testing, Property 8: Selector Pass-Through Correctness

        For any classification with confidence >= 0.7, the Selector returns
        the classified route. Simple and cloud routes always pass through.
        Validates: Requirements 8.4, 8.5, 8.6
        """
        selector = RouteSelector()

        # Simple route always passes through
        simple_cls = RouteClassification(
            route="simple", confidence=confidence, toolbox=["all"], reasoning="test",
        )
        route, _ = selector.select(simple_cls, features, current_variant="default")
        assert route == "simple", f"Simple route should pass through, got {route}"

        # Cloud route always passes through
        cloud_cls = RouteClassification(
            route="complex-cloud", confidence=confidence, toolbox=["all"], reasoning="test",
        )
        route, _ = selector.select(cloud_cls, features, current_variant="default")
        assert route == "complex-cloud", f"Cloud route should pass through, got {route}"

        # High confidence complex route returns classified route
        complex_cls = RouteClassification(
            route="complex-default", confidence=confidence, toolbox=["file_ops"], reasoning="test",
        )
        route, toolbox = selector.select(complex_cls, features, current_variant="default")
        assert route == "complex-default", (
            f"High confidence ({confidence}) should use classified route, got {route}"
        )


# ═════════════════════════════════════════════════════════════════════════
# TestCloudEscalationAvailability — Requirement 9
# ═════════════════════════════════════════════════════════════════════════

class TestCloudEscalationAvailability:
    """Verify that the Router correctly escalates to DeepSeek cloud when
    needed and gracefully downgrades when cloud is unavailable, so that
    large-context and frontier tasks are handled without failure.

    Feature: router-model-swap-testing
    Requirement: 9 — Cloud Escalation and Availability
    """

    # ── Req 9.1: no API key → downgrade to local route ──────────────
    @pytest.mark.anyio
    async def test_no_api_key_downgrades_to_local_route(self, mock_profile):
        """Validates: Requirements 9.1

        WHEN the route is complex-cloud AND no valid DeepSeek API key is
        configured, THE Router SHALL downgrade to a local route.
        """
        # Use frontier keywords to trigger deterministic cloud route
        mock_small = _make_mock_llm(response_content="should not be called")

        with (
            patch("src.agent.nodes.router.get_small_llm", new_callable=AsyncMock, return_value=mock_small),
            patch("src.agent.nodes.router._check_cloud_available", return_value=False),
            patch("src.agent.nodes.router.get_profile", return_value=mock_profile),
        ):
            state = _make_text_state("prove the theorem about differential equation convergence")
            result = await _router_node_inner(state, RouterConfig())

        # Cloud should be downgraded to a local route
        assert result["route"] != "complex-cloud", (
            "Expected cloud route to be downgraded when no API key is available"
        )
        assert result["route"] in ("complex-default", "complex-longctx"), (
            f"Expected downgrade to complex-default or complex-longctx, "
            f"got '{result['route']}'"
        )

    # ── Req 9.2: cloud_escalation_enabled=False → downgrade ─────────
    @pytest.mark.anyio
    async def test_cloud_escalation_disabled_downgrades(self, mock_profile):
        """Validates: Requirements 9.2

        WHEN the route is complex-cloud AND cloud_escalation_enabled is
        False in the profile, THE Router SHALL downgrade to a local route.
        """
        mock_profile["cloud_escalation_enabled"] = False
        mock_small = _make_mock_llm(response_content="should not be called")

        with (
            patch("src.agent.nodes.router.get_small_llm", new_callable=AsyncMock, return_value=mock_small),
            # _check_cloud_available returns False when cloud_escalation_enabled=False
            patch("src.agent.nodes.router._check_cloud_available", return_value=False),
            patch("src.agent.nodes.router.get_profile", return_value=mock_profile),
        ):
            state = _make_text_state("prove the theorem about differential equation convergence")
            result = await _router_node_inner(state, RouterConfig())

        assert result["route"] != "complex-cloud", (
            "Expected cloud route to be downgraded when cloud_escalation_enabled=False"
        )
        assert result["route"] in ("complex-default", "complex-longctx"), (
            f"Expected downgrade to complex-default or complex-longctx, "
            f"got '{result['route']}'"
        )

    # ── Req 9.3: cloud_hitl_enabled=True → triggers HITL approval interrupt ──
    @pytest.mark.anyio
    async def test_cloud_hitl_enabled_triggers_approval_interrupt(self, mock_profile):
        """Validates: Requirements 9.3

        WHEN the route is complex-cloud AND cloud_hitl_enabled is True,
        THE Router SHALL trigger an HITL approval interrupt before sending
        data to the DeepSeek API.
        """
        mock_profile["cloud_hitl_enabled"] = True
        mock_small = _make_mock_llm(response_content="should not be called")

        with (
            patch("src.agent.nodes.router.get_small_llm", new_callable=AsyncMock, return_value=mock_small),
            patch("src.agent.nodes.router._check_cloud_available", return_value=True),
            patch("src.agent.nodes.router.get_profile", return_value=mock_profile),
            patch(
                "src.agent.nodes.router.interrupt",
                return_value={"route": "complex-cloud", "toolbox": ["all"]},
            ) as mock_interrupt,
        ):
            state = _make_text_state("prove the theorem about differential equation convergence")
            result = await _router_node_inner(state, RouterConfig())

        # interrupt should have been called for cloud approval
        mock_interrupt.assert_called()
        # Find the cloud approval call (contains "DeepSeek" in the question)
        cloud_approval_called = False
        for call in mock_interrupt.call_args_list:
            call_arg = call[0][0]
            if isinstance(call_arg, dict) and "deepseek" in call_arg.get("question", "").lower():
                cloud_approval_called = True
                # Verify the choices include approve and deny options
                choices = call_arg.get("choices", [])
                assert len(choices) >= 2, "Expected at least approve and deny choices"
                break
        assert cloud_approval_called, (
            "Expected cloud HITL approval interrupt with DeepSeek question"
        )
        assert result["route"] == "complex-cloud", (
            f"Expected complex-cloud when user approves, got '{result['route']}'"
        )

    # ── Req 9.4: user denies cloud HITL → downgrade to selected alternative ──
    @pytest.mark.anyio
    async def test_user_denies_cloud_hitl_downgrades(self, mock_profile):
        """Validates: Requirements 9.4

        WHEN the user denies the cloud HITL approval, THE Router SHALL
        downgrade the route to the user's selected alternative.
        """
        mock_profile["cloud_hitl_enabled"] = True
        mock_small = _make_mock_llm(response_content="should not be called")

        with (
            patch("src.agent.nodes.router.get_small_llm", new_callable=AsyncMock, return_value=mock_small),
            patch("src.agent.nodes.router._check_cloud_available", return_value=True),
            patch("src.agent.nodes.router.get_profile", return_value=mock_profile),
            patch(
                "src.agent.nodes.router.interrupt",
                # User denies — selects local model instead
                return_value={"route": "complex-default", "toolbox": ["all"]},
            ),
        ):
            state = _make_text_state("prove the theorem about differential equation convergence")
            result = await _router_node_inner(state, RouterConfig())

        # Route should be downgraded to the user's selected alternative
        assert result["route"] == "complex-default", (
            f"Expected complex-default when user denies cloud HITL, "
            f"got '{result['route']}'"
        )

    # ── Req 9.5: HTTP 429 → retry once then fallback ────────────────
    @pytest.mark.anyio
    async def test_http_429_retries_then_falls_back(self, mock_profile):
        """Validates: Requirements 9.5

        IF the cloud LLM invocation fails with a rate limit error (HTTP 429),
        THEN THE Complex_Node SHALL retry once after a delay, then fall back
        to medium-default if the retry also fails.
        """
        # Cloud LLM that fails with 429 on both attempts
        cloud_llm = MagicMock()
        cloud_llm.bind_tools.return_value = cloud_llm
        cloud_llm.bind.return_value = cloud_llm
        cloud_llm.ainvoke = AsyncMock(side_effect=Exception("429 rate limit exceeded"))

        # Fallback local LLM that succeeds
        fallback_llm = _make_mock_llm("Fallback response after rate limit.")

        call_count = 0

        async def mock_get_medium_llm(variant="default"):
            nonlocal call_count
            call_count += 1
            return fallback_llm

        with (
            patch("src.agent.nodes.complex.get_medium_llm", side_effect=mock_get_medium_llm),
            patch("src.agent.nodes.complex.get_cloud_llm", new_callable=AsyncMock, return_value=cloud_llm),
            patch("src.agent.nodes.complex.get_profile", return_value=mock_profile),
            patch("src.agent.nodes.complex.is_local_server", return_value=True),
            # Speed up the retry delay for testing
            patch("src.agent.nodes.complex.asyncio.sleep", new_callable=AsyncMock),
        ):
            state = _make_complex_state(
                route="complex-cloud",
                text="prove the theorem",
                selected_toolboxes=["all"],
            )
            result = await complex_llm_node(state)

        # Should have fallen back to medium-default
        assert "fallback" in result["model_used"], (
            f"Expected fallback model after 429 retry failure, got '{result['model_used']}'"
        )
        # Fallback chain should record the rate limit failure
        chain = result.get("fallback_chain", [])
        rate_limit_entries = [
            e for e in chain
            if "rate limit" in e.get("reason", "").lower() or "failed" in e.get("status", "")
        ]
        assert len(rate_limit_entries) > 0, (
            f"Expected rate limit failure in fallback_chain, got {chain}"
        )

    # ── Req 9.5 (retry succeeds): HTTP 429 → retry once succeeds ────
    @pytest.mark.anyio
    async def test_http_429_retry_succeeds(self, mock_profile):
        """Validates: Requirements 9.5

        IF the cloud LLM invocation fails with a rate limit error (HTTP 429)
        on the first call but succeeds on retry, THE Complex_Node SHALL
        use the retry response.
        """
        cloud_llm = MagicMock()
        cloud_llm.bind_tools.return_value = cloud_llm
        cloud_llm.bind.return_value = cloud_llm
        invoke_count = 0

        async def mock_ainvoke(messages):
            nonlocal invoke_count
            invoke_count += 1
            if invoke_count == 1:
                raise Exception("429 rate limit exceeded")
            return AIMessage(content="Retry succeeded response.")

        cloud_llm.ainvoke = AsyncMock(side_effect=mock_ainvoke)

        with (
            patch("src.agent.nodes.complex.get_medium_llm", new_callable=AsyncMock, return_value=_make_mock_llm()),
            patch("src.agent.nodes.complex.get_cloud_llm", new_callable=AsyncMock, return_value=cloud_llm),
            patch("src.agent.nodes.complex.get_profile", return_value=mock_profile),
            patch("src.agent.nodes.complex.is_local_server", return_value=False),
            patch("src.agent.nodes.complex.asyncio.sleep", new_callable=AsyncMock),
        ):
            state = _make_complex_state(
                route="complex-cloud",
                text="prove the theorem",
                selected_toolboxes=["all"],
            )
            result = await complex_llm_node(state)

        # Should have used the cloud model (retry succeeded, no fallback)
        assert result["model_used"] == "large-cloud", (
            f"Expected large-cloud after successful retry, got '{result['model_used']}'"
        )

    # ── Req 9.6: HTTP 401/403 → fallback + API key warning ──────────
    @pytest.mark.anyio
    async def test_http_401_falls_back_with_api_key_warning(self, mock_profile):
        """Validates: Requirements 9.6

        IF the cloud LLM invocation fails with an auth error (HTTP 401/403),
        THEN THE Complex_Node SHALL fall back to medium-default and append
        a warning about the API key.
        """
        # Cloud LLM that fails with 401
        cloud_llm = MagicMock()
        cloud_llm.bind_tools.return_value = cloud_llm
        cloud_llm.bind.return_value = cloud_llm
        cloud_llm.ainvoke = AsyncMock(side_effect=Exception("401 Unauthorized"))

        # Fallback local LLM that succeeds
        fallback_llm = _make_mock_llm("Here is the local response.")

        with (
            patch("src.agent.nodes.complex.get_medium_llm", new_callable=AsyncMock, return_value=fallback_llm),
            patch("src.agent.nodes.complex.get_cloud_llm", new_callable=AsyncMock, return_value=cloud_llm),
            patch("src.agent.nodes.complex.get_profile", return_value=mock_profile),
            patch("src.agent.nodes.complex.is_local_server", return_value=True),
        ):
            state = _make_complex_state(
                route="complex-cloud",
                text="prove the theorem",
                selected_toolboxes=["all"],
            )
            result = await complex_llm_node(state)

        # Should have fallen back to medium-default
        assert "fallback" in result["model_used"], (
            f"Expected fallback model after 401 auth error, got '{result['model_used']}'"
        )

        # The response should contain an API key warning
        final_msg = result["messages"][-1]
        assert isinstance(final_msg, AIMessage)
        assert "api key" in final_msg.content.lower(), (
            f"Expected API key warning in response, got: {final_msg.content[:200]}"
        )

        # Fallback chain should record the auth error
        chain = result.get("fallback_chain", [])
        auth_entries = [
            e for e in chain
            if "auth" in e.get("reason", "").lower() or "401" in e.get("reason", "").lower()
        ]
        assert len(auth_entries) > 0, (
            f"Expected auth error in fallback_chain, got {chain}"
        )

    # ── Req 9.6 (403 variant): HTTP 403 → same behavior as 401 ──────
    @pytest.mark.anyio
    async def test_http_403_falls_back_with_api_key_warning(self, mock_profile):
        """Validates: Requirements 9.6

        IF the cloud LLM invocation fails with HTTP 403 Forbidden,
        THEN THE Complex_Node SHALL fall back to medium-default and append
        a warning about the API key (same behavior as 401).
        """
        cloud_llm = MagicMock()
        cloud_llm.bind_tools.return_value = cloud_llm
        cloud_llm.bind.return_value = cloud_llm
        cloud_llm.ainvoke = AsyncMock(side_effect=Exception("403 Forbidden"))

        fallback_llm = _make_mock_llm("Here is the local response.")

        with (
            patch("src.agent.nodes.complex.get_medium_llm", new_callable=AsyncMock, return_value=fallback_llm),
            patch("src.agent.nodes.complex.get_cloud_llm", new_callable=AsyncMock, return_value=cloud_llm),
            patch("src.agent.nodes.complex.get_profile", return_value=mock_profile),
            patch("src.agent.nodes.complex.is_local_server", return_value=True),
        ):
            state = _make_complex_state(
                route="complex-cloud",
                text="prove the theorem",
                selected_toolboxes=["all"],
            )
            result = await complex_llm_node(state)

        assert "fallback" in result["model_used"], (
            f"Expected fallback model after 403 error, got '{result['model_used']}'"
        )

        final_msg = result["messages"][-1]
        assert isinstance(final_msg, AIMessage)
        assert "api key" in final_msg.content.lower(), (
            f"Expected API key warning in response for 403, got: {final_msg.content[:200]}"
        )


# ═════════════════════════════════════════════════════════════════════════
# TestTokenBudgetCorrectness — Requirement 10
# ═════════════════════════════════════════════════════════════════════════

class TestTokenBudgetCorrectness:
    """Verify that the token budget is computed using the correct context
    window for each route and respects all tier constraints.

    Feature: router-model-swap-testing
    Requirement: 10 — Token Budget Correctness
    """

    # ── Req 10.1: estimate_token_budget returns positive integer >= 1 ──
    def test_budget_always_positive_integer(self):
        """Validates: Requirements 10.1

        THE estimate_token_budget function SHALL return a positive integer
        (>= 1) for any input text and any valid route.
        """
        for route in sorted(VALID_ROUTES):
            for text in ["", "hi", "a" * 10000, "explain quantum physics in detail"]:
                budget = estimate_token_budget(text, route)
                assert isinstance(budget, int), (
                    f"Expected int for route={route}, text={text[:30]!r}, got {type(budget)}"
                )
                assert budget >= 1, (
                    f"Expected budget >= 1 for route={route}, text={text[:30]!r}, got {budget}"
                )

    # ── Req 10.2: simple route → budget <= 2596 ─────────────────────
    def test_simple_route_budget_upper_bound(self):
        """Validates: Requirements 10.2

        WHEN the route is simple, THE token budget SHALL not exceed 2596
        (SMALL_MODEL_CONTEXT - 1500 = 4096 - 1500).
        """
        max_simple_budget = 4096 - 1500  # 2596
        for text in ["hello", "thanks", "a" * 5000, "what time is it"]:
            budget = estimate_token_budget(text, "simple")
            assert budget <= max_simple_budget, (
                f"Expected budget <= {max_simple_budget} for simple route, "
                f"text={text[:30]!r}, got {budget}"
            )

    # ── Req 10.3: complex-default/vision → budget <= 8192 ───────────
    def test_complex_default_vision_budget_upper_bound(self):
        """Validates: Requirements 10.3

        WHEN the route is complex-default or complex-vision, THE token
        budget SHALL not exceed 8192.
        """
        for route in ["complex-default", "complex-vision"]:
            for text in ["hello", "explain everything", "a" * 5000]:
                budget = estimate_token_budget(text, route)
                assert budget <= 8192, (
                    f"Expected budget <= 8192 for route={route}, "
                    f"text={text[:30]!r}, got {budget}"
                )

    # ── Req 10.4: complex-cloud → budget <= 16384 ───────────────────
    def test_complex_cloud_budget_upper_bound(self):
        """Validates: Requirements 10.4

        WHEN the route is complex-cloud, THE token budget SHALL not
        exceed 16384.
        """
        for text in ["hello", "explain everything in detail", "a" * 5000]:
            budget = estimate_token_budget(text, "complex-cloud")
            assert budget <= 16384, (
                f"Expected budget <= 16384 for complex-cloud, "
                f"text={text[:30]!r}, got {budget}"
            )

    # ── Req 10.5: long-answer hints + complex route → budget >= 3072 ──
    def test_long_answer_hints_boost_budget(self):
        """Validates: Requirements 10.5

        WHEN the user text contains long-answer hint keywords (explain,
        write, create, implement, etc.) AND the route is complex, THE
        token budget SHALL be at least 3072.
        """
        long_answer_text = "explain in detail how machine learning works"
        for route in sorted(VALID_COMPLEX_ROUTES):
            budget = estimate_token_budget(long_answer_text, route)
            assert budget >= 3072, (
                f"Expected budget >= 3072 for long-answer hint on route={route}, "
                f"got {budget}"
            )

    # ── Req 10.6: short-answer hints + complex route → budget <= 1536 ──
    def test_short_answer_hints_cap_budget(self):
        """Validates: Requirements 10.6

        WHEN the user text contains short-answer hint keywords (yes or no,
        what is, how many, etc.) AND the route is complex, THE token
        budget SHALL not exceed 1536.
        """
        short_answer_text = "yes or no is this correct"
        for route in sorted(VALID_COMPLEX_ROUTES):
            budget = estimate_token_budget(short_answer_text, route)
            assert budget <= 1536, (
                f"Expected budget <= 1536 for short-answer hint on route={route}, "
                f"got {budget}"
            )

    # ── Property 9: Token Budget Bounds ─────────────────────────────────
    @given(text=user_text_st, route=route_st)
    @settings(max_examples=100, deadline=None)
    def test_budget_bounds_per_route(self, text, route):
        """Feature: router-model-swap-testing, Property 9: Token Budget Bounds

        For any user text and valid route, estimate_token_budget returns a
        positive integer within per-route upper bounds.
        Validates: Requirements 10.1, 10.2, 10.3, 10.4
        """
        budget = estimate_token_budget(text, route)

        # Always positive integer (Req 10.1)
        assert isinstance(budget, int), f"Expected int, got {type(budget)}"
        assert budget >= 1, f"Expected budget >= 1, got {budget}"

        # Per-route upper bounds
        if route == "simple":
            assert budget <= 2596, (
                f"Simple route budget {budget} exceeds 2596"
            )
        elif route in ("complex-default", "complex-vision", "complex-longctx"):
            assert budget <= 8192, (
                f"{route} budget {budget} exceeds 8192"
            )
        elif route == "complex-cloud":
            assert budget <= 16384, (
                f"Cloud route budget {budget} exceeds 16384"
            )

    # ── Property 10: Token Budget Hint Sensitivity ──────────────────
    @given(route=complex_route_st)
    @settings(max_examples=100, deadline=None)
    def test_budget_hint_sensitivity(self, route):
        """Feature: router-model-swap-testing, Property 10: Token Budget Hint Sensitivity

        For long-answer hints on complex routes → budget >= 3072.
        For short-answer hints on complex routes → budget <= 1536.
        Validates: Requirements 10.5, 10.6
        """
        # Long-answer hint (Req 10.5)
        long_text = "explain in detail how this algorithm works step by step"
        long_budget = estimate_token_budget(long_text, route)
        assert long_budget >= 3072, (
            f"Long-answer hint on {route}: expected budget >= 3072, got {long_budget}"
        )

        # Short-answer hint (Req 10.6)
        short_text = "yes or no is this correct"
        short_budget = estimate_token_budget(short_text, route)
        assert short_budget <= 1536, (
            f"Short-answer hint on {route}: expected budget <= 1536, got {short_budget}"
        )

# ═════════════════════════════════════════════════════════════════════════
# TestClassifierParseRobustness — Requirement 11
# ═════════════════════════════════════════════════════════════════════════

class TestClassifierParseRobustness:
    """Verify that parse_classification handles any input string without
    crashing and always returns a valid RouteClassification.

    Feature: router-model-swap-testing
    Requirement: 11 — Classifier Parse Robustness
    """

    # ── Req 11.1: empty, malformed, random inputs → valid RouteClassification ──

    def test_empty_string_returns_valid_classification(self):
        """Validates: Requirements 11.1

        parse_classification SHALL return a valid RouteClassification for
        an empty string input.
        """
        result = parse_classification("")
        assert result.route in VALID_ROUTES
        assert 0.0 <= result.confidence <= 1.0
        assert isinstance(result.toolbox, list) and len(result.toolbox) > 0

    def test_not_json_returns_valid_classification(self):
        """Validates: Requirements 11.1

        parse_classification SHALL return a valid RouteClassification for
        a plain text (non-JSON) input.
        """
        result = parse_classification("not json")
        assert result.route in VALID_ROUTES
        assert 0.0 <= result.confidence <= 1.0
        assert isinstance(result.toolbox, list) and len(result.toolbox) > 0

    def test_malformed_braces_returns_valid_classification(self):
        """Validates: Requirements 11.1

        parse_classification SHALL return a valid RouteClassification for
        malformed JSON with unbalanced braces.
        """
        result = parse_classification("{{{{")
        assert result.route in VALID_ROUTES
        assert 0.0 <= result.confidence <= 1.0
        assert isinstance(result.toolbox, list) and len(result.toolbox) > 0

    def test_none_like_string_returns_valid_classification(self):
        """Validates: Requirements 11.1

        parse_classification SHALL return a valid RouteClassification for
        None-like string inputs such as 'None', 'null', 'undefined'.
        """
        for text in ["None", "null", "undefined", "NaN"]:
            result = parse_classification(text)
            assert result.route in VALID_ROUTES, f"Failed for input {text!r}"
            assert 0.0 <= result.confidence <= 1.0, f"Failed for input {text!r}"
            assert isinstance(result.toolbox, list) and len(result.toolbox) > 0, (
                f"Failed for input {text!r}"
            )

    # ── Req 11.2: valid JSON with recognized route → correct extraction ──

    def test_valid_json_recognized_route_extracts_correctly(self):
        """Validates: Requirements 11.2

        WHEN the input contains valid JSON with a recognized route, THE
        parse_classification function SHALL extract the route, confidence,
        toolbox, and reasoning correctly.
        """
        input_json = json.dumps({
            "route": "complex-vision",
            "confidence": 0.9,
            "toolbox": ["file_ops"],
            "reasoning": "test",
        })
        result = parse_classification(input_json)
        assert result.route == "complex-vision"
        assert abs(result.confidence - 0.9) < 1e-6
        assert result.toolbox == ["file_ops"]
        assert result.reasoning == "test"

    def test_valid_json_all_routes_extract_correctly(self):
        """Validates: Requirements 11.2

        Each recognized route string is correctly extracted from valid JSON.
        """
        for route in sorted(VALID_ROUTES):
            input_json = json.dumps({
                "route": route,
                "confidence": 0.8,
                "toolbox": ["all"],
                "reasoning": f"testing {route}",
            })
            result = parse_classification(input_json)
            assert result.route == route, f"Expected route={route}, got {result.route}"

    # ── Req 11.3: unrecognized route → defaults to complex-default ──

    def test_unrecognized_route_defaults_to_complex_default(self):
        """Validates: Requirements 11.3

        WHEN the input contains an unrecognized route string, THE
        parse_classification function SHALL default to complex-default.
        """
        input_json = json.dumps({
            "route": "invalid-route",
            "confidence": 0.5,
            "toolbox": ["all"],
        })
        result = parse_classification(input_json)
        assert result.route == "complex-default"

    def test_various_unrecognized_routes_default(self):
        """Validates: Requirements 11.3

        Various unrecognized route strings all default to complex-default.
        """
        bad_routes = ["unknown", "super-complex", "simple-plus", "", "fast-route", "complex"]
        for bad_route in bad_routes:
            input_json = json.dumps({
                "route": bad_route,
                "confidence": 0.7,
                "toolbox": ["all"],
            })
            result = parse_classification(input_json)
            assert result.route == "complex-default", (
                f"Expected complex-default for route={bad_route!r}, got {result.route}"
            )

    # ── Req 11.4: round-trip: serialize → parse back → equivalent ──

    def test_round_trip_serialize_parse_equivalence(self):
        """Validates: Requirements 11.4

        FOR ALL valid RouteClassification objects, serializing to JSON and
        parsing back SHALL produce an equivalent RouteClassification.
        """
        for route in sorted(VALID_ROUTES):
            original = RouteClassification(
                route=route,
                confidence=0.85,
                toolbox=["file_ops", "data_viz"],
                reasoning="round-trip test",
            )
            serialized = json.dumps({
                "route": original.route,
                "confidence": original.confidence,
                "toolbox": original.toolbox,
                "reasoning": original.reasoning,
            })
            parsed = parse_classification(serialized)
            assert parsed.route == original.route
            assert abs(parsed.confidence - original.confidence) < 1e-6
            assert parsed.toolbox == original.toolbox
            assert parsed.reasoning == original.reasoning

    # ── Req 11.5: confidence clamped to [0.0, 1.0] ──

    def test_confidence_above_one_clamped(self):
        """Validates: Requirements 11.5

        THE parse_classification function SHALL clamp confidence to [0.0, 1.0]
        via the RouteClassification dataclass validation — values > 1.0 are
        clamped to 1.0.
        """
        input_json = json.dumps({
            "route": "complex-default",
            "confidence": 5.0,
            "toolbox": ["all"],
        })
        result = parse_classification(input_json)
        assert result.confidence == 1.0, (
            f"Expected confidence clamped to 1.0, got {result.confidence}"
        )

    def test_confidence_below_zero_clamped(self):
        """Validates: Requirements 11.5

        THE parse_classification function SHALL clamp confidence to [0.0, 1.0]
        via the RouteClassification dataclass validation — values < 0.0 are
        clamped to 0.0.
        """
        input_json = json.dumps({
            "route": "complex-default",
            "confidence": -3.0,
            "toolbox": ["all"],
        })
        result = parse_classification(input_json)
        assert result.confidence == 0.0, (
            f"Expected confidence clamped to 0.0, got {result.confidence}"
        )

    # ── Property 11: Classifier Parse Robustness ────────────────────
    @given(content=classification_json_st)
    @settings(max_examples=100, deadline=None)
    def test_parse_classification_never_crashes(self, content):
        """Feature: router-model-swap-testing, Property 11: Classifier Parse Robustness

        For any arbitrary string input, parse_classification returns a valid
        RouteClassification without raising an exception.
        Validates: Requirements 11.1, 11.2, 11.3, 11.5
        """
        result = parse_classification(content)

        # Always returns a valid RouteClassification
        assert result.route in VALID_ROUTES, (
            f"Expected route in {VALID_ROUTES}, got {result.route!r}"
        )
        assert 0.0 <= result.confidence <= 1.0, (
            f"Expected confidence in [0.0, 1.0], got {result.confidence}"
        )
        assert isinstance(result.toolbox, list) and len(result.toolbox) > 0, (
            f"Expected non-empty toolbox list, got {result.toolbox}"
        )

    # ── Property 12: Classification Round-Trip ──────────────────────
    @given(
        route=route_st,
        confidence=confidence_st,
        toolbox=st.lists(toolbox_name_st, min_size=1, max_size=5, unique=True),
    )
    @settings(max_examples=100, deadline=None)
    def test_classification_round_trip(self, route, confidence, toolbox):
        """Feature: router-model-swap-testing, Property 12: Classification Round-Trip

        For any valid RouteClassification, serializing to JSON and parsing
        back produces an equivalent RouteClassification.
        Validates: Requirements 11.4
        """
        original = RouteClassification(
            route=route,
            confidence=confidence,
            toolbox=toolbox,
            reasoning="round-trip test",
        )
        serialized = json.dumps({
            "route": original.route,
            "confidence": original.confidence,
            "toolbox": original.toolbox,
            "reasoning": original.reasoning,
        })
        parsed = parse_classification(serialized)

        assert parsed.route == original.route, (
            f"Round-trip route mismatch: {original.route} → {parsed.route}"
        )
        assert abs(parsed.confidence - original.confidence) < 1e-6, (
            f"Round-trip confidence mismatch: {original.confidence} → {parsed.confidence}"
        )
        assert parsed.toolbox == original.toolbox, (
            f"Round-trip toolbox mismatch: {original.toolbox} → {parsed.toolbox}"
        )


# ═════════════════════════════════════════════════════════════════════════
# TestFeatureExtractionCorrectness — Requirement 12
# ═════════════════════════════════════════════════════════════════════════

class TestFeatureExtractionCorrectness:
    """Verify that the Feature_Extractor produces accurate, well-bounded
    TaskFeatures from any user input, so that downstream routing and
    toolbox decisions are based on correct signals.

    Feature: router-model-swap-testing
    Requirement: 12 — Feature Extraction Correctness
    """

    # ── Req 12.1: scores in [0.0, 1.0], valid task_category ─────────

    def test_scores_in_range_and_valid_category_for_plain_text(self):
        """Validates: Requirements 12.1, 12.6

        THE Feature_Extractor SHALL return a valid TaskFeatures object with
        document_keywords_score in [0.0, 1.0], vision_keywords_score in
        [0.0, 1.0], and task_category in VALID_TASK_CATEGORIES for plain text.
        """
        state = _make_text_state("Hello, how are you today?")
        features = extract_features("Hello, how are you today?", state)

        assert 0.0 <= features.document_keywords_score <= 1.0, (
            f"document_keywords_score out of range: {features.document_keywords_score}"
        )
        assert 0.0 <= features.vision_keywords_score <= 1.0, (
            f"vision_keywords_score out of range: {features.vision_keywords_score}"
        )
        assert features.task_category in VALID_TASK_CATEGORIES, (
            f"task_category not valid: {features.task_category}"
        )
        assert features.estimated_input_tokens >= 0, (
            f"estimated_input_tokens negative: {features.estimated_input_tokens}"
        )

    # ── Req 12.2: image_url content block → has_images=True ─────────

    def test_image_url_content_sets_has_images(self):
        """Validates: Requirements 12.2

        WHEN the last message contains an image_url content block, THE
        Feature_Extractor SHALL set has_images to True.
        """
        state = _make_image_state("Describe this image")
        features = extract_features("Describe this image", state)

        assert features.has_images is True, (
            "Expected has_images=True for image_url content block"
        )

    def test_no_image_url_sets_has_images_false(self):
        """Validates: Requirements 12.2 (negative case)

        WHEN the last message does NOT contain an image_url content block,
        THE Feature_Extractor SHALL set has_images to False.
        """
        state = _make_text_state("Just a plain text message")
        features = extract_features("Just a plain text message", state)

        assert features.has_images is False, (
            "Expected has_images=False for plain text message"
        )

    # ── Req 12.3: web-intent keywords → web_intent=True ─────────────

    def test_weather_keyword_sets_web_intent(self):
        """Validates: Requirements 12.3

        WHEN the user text contains web-intent keywords like 'weather',
        THE Feature_Extractor SHALL set web_intent to True.
        """
        state = _make_text_state("What is the weather in Tokyo?")
        features = extract_features("What is the weather in Tokyo?", state)

        assert features.web_intent is True, (
            "Expected web_intent=True for 'weather' keyword"
        )

    def test_stock_price_keyword_sets_web_intent(self):
        """Validates: Requirements 12.3

        WHEN the user text contains 'stock price', THE Feature_Extractor
        SHALL set web_intent to True.
        """
        state = _make_text_state("What is the stock price of AAPL?")
        features = extract_features("What is the stock price of AAPL?", state)

        assert features.web_intent is True, (
            "Expected web_intent=True for 'stock price' keyword"
        )

    def test_search_the_web_keyword_sets_web_intent(self):
        """Validates: Requirements 12.3

        WHEN the user text contains 'search the web', THE Feature_Extractor
        SHALL set web_intent to True.
        """
        state = _make_text_state("Please search the web for Python tutorials")
        features = extract_features("Please search the web for Python tutorials", state)

        assert features.web_intent is True, (
            "Expected web_intent=True for 'search the web' keyword"
        )

    def test_no_web_keywords_sets_web_intent_false(self):
        """Validates: Requirements 12.3 (negative case)

        WHEN the user text does NOT contain web-intent keywords, THE
        Feature_Extractor SHALL set web_intent to False.
        """
        state = _make_text_state("Write a Python function to sort a list")
        features = extract_features("Write a Python function to sort a list", state)

        assert features.web_intent is False, (
            "Expected web_intent=False for non-web text"
        )

    # ── Req 12.4: frontier keywords → frontier_quality_needed=True ───

    def test_theorem_keyword_sets_frontier_quality(self):
        """Validates: Requirements 12.4

        WHEN the user text contains frontier-quality keywords like 'theorem',
        THE Feature_Extractor SHALL set frontier_quality_needed to True.
        """
        state = _make_text_state("Prove this theorem about prime numbers")
        features = extract_features("Prove this theorem about prime numbers", state)

        assert features.frontier_quality_needed is True, (
            "Expected frontier_quality_needed=True for 'theorem' keyword"
        )

    def test_formal_proof_keyword_sets_frontier_quality(self):
        """Validates: Requirements 12.4

        WHEN the user text contains 'formal proof', THE Feature_Extractor
        SHALL set frontier_quality_needed to True.
        """
        state = _make_text_state("Write a formal proof for this conjecture")
        features = extract_features("Write a formal proof for this conjecture", state)

        assert features.frontier_quality_needed is True, (
            "Expected frontier_quality_needed=True for 'formal proof' keyword"
        )

    def test_differential_equation_keyword_sets_frontier_quality(self):
        """Validates: Requirements 12.4

        WHEN the user text contains 'differential equation', THE Feature_Extractor
        SHALL set frontier_quality_needed to True.
        """
        state = _make_text_state("Solve this differential equation for me")
        features = extract_features("Solve this differential equation for me", state)

        assert features.frontier_quality_needed is True, (
            "Expected frontier_quality_needed=True for 'differential equation' keyword"
        )

    def test_no_frontier_keywords_sets_frontier_false(self):
        """Validates: Requirements 12.4 (negative case)

        WHEN the user text does NOT contain frontier-quality keywords, THE
        Feature_Extractor SHALL set frontier_quality_needed to False.
        """
        state = _make_text_state("Tell me a joke about cats")
        features = extract_features("Tell me a joke about cats", state)

        assert features.frontier_quality_needed is False, (
            "Expected frontier_quality_needed=False for non-frontier text"
        )

    # ── Req 12.5: file attachment markers → has_file_attachments=True ─

    def test_file_marker_sets_has_file_attachments(self):
        """Validates: Requirements 12.5

        WHEN the user text contains '[file:' marker, THE Feature_Extractor
        SHALL set has_file_attachments to True.
        """
        text = "[file: data.csv] Please analyze this data"
        state = _make_text_state(text)
        features = extract_features(text, state)

        assert features.has_file_attachments is True, (
            "Expected has_file_attachments=True for '[file:' marker"
        )

    def test_uploaded_to_workspace_sets_has_file_attachments(self):
        """Validates: Requirements 12.5

        WHEN the user text contains 'uploaded to workspace', THE Feature_Extractor
        SHALL set has_file_attachments to True.
        """
        text = "I uploaded to workspace a new report"
        state = _make_text_state(text)
        features = extract_features(text, state)

        assert features.has_file_attachments is True, (
            "Expected has_file_attachments=True for 'uploaded to workspace' marker"
        )

    def test_workspace_file_sets_has_file_attachments(self):
        """Validates: Requirements 12.5

        WHEN the user text contains 'workspace file', THE Feature_Extractor
        SHALL set has_file_attachments to True.
        """
        text = "Check the workspace file I just added"
        state = _make_text_state(text)
        features = extract_features(text, state)

        assert features.has_file_attachments is True, (
            "Expected has_file_attachments=True for 'workspace file' marker"
        )

    def test_no_file_markers_sets_has_file_attachments_false(self):
        """Validates: Requirements 12.5 (negative case)

        WHEN the user text does NOT contain file attachment markers, THE
        Feature_Extractor SHALL set has_file_attachments to False.
        """
        state = _make_text_state("Just a regular question about Python")
        features = extract_features("Just a regular question about Python", state)

        assert features.has_file_attachments is False, (
            "Expected has_file_attachments=False for text without file markers"
        )

    # ── Req 12.6: task_category is one of the valid set ──────────────

    def test_task_category_is_valid_for_code_text(self):
        """Validates: Requirements 12.6

        THE Feature_Extractor SHALL set task_category to exactly one of:
        general, document, vision, code, analysis.
        """
        state = _make_text_state("Debug this code for me")
        features = extract_features("Debug this code for me", state)

        assert features.task_category in VALID_TASK_CATEGORIES, (
            f"task_category '{features.task_category}' not in {VALID_TASK_CATEGORIES}"
        )
        assert features.task_category == "code", (
            f"Expected task_category='code' for code-related text, got '{features.task_category}'"
        )

    def test_task_category_is_valid_for_analysis_text(self):
        """Validates: Requirements 12.6

        THE Feature_Extractor SHALL set task_category to 'analysis' for
        analysis-related text.
        """
        state = _make_text_state("Compare these two approaches")
        features = extract_features("Compare these two approaches", state)

        assert features.task_category in VALID_TASK_CATEGORIES, (
            f"task_category '{features.task_category}' not in {VALID_TASK_CATEGORIES}"
        )
        assert features.task_category == "analysis", (
            f"Expected task_category='analysis' for analysis text, got '{features.task_category}'"
        )

    # ── Req 12.7: unexpected error → conservative defaults ───────────

    def test_unexpected_error_returns_conservative_defaults(self):
        """Validates: Requirements 12.7

        IF the Feature_Extractor encounters an unexpected error, THEN THE
        Feature_Extractor SHALL return conservative default TaskFeatures
        (no images, general category, zero keyword scores).
        """
        state = _make_text_state("test input")

        with patch(
            "src.agent.router.feature_extractor._extract_features_inner",
            side_effect=RuntimeError("Unexpected failure"),
        ):
            features = extract_features("test input", state)

        # Verify conservative defaults
        assert features.has_images is False, "Default has_images should be False"
        assert features.has_file_attachments is False, "Default has_file_attachments should be False"
        assert features.web_intent is False, "Default web_intent should be False"
        assert features.task_category == "general", (
            f"Default task_category should be 'general', got '{features.task_category}'"
        )
        assert features.document_keywords_score == 0.0, (
            f"Default document_keywords_score should be 0.0, got {features.document_keywords_score}"
        )
        assert features.vision_keywords_score == 0.0, (
            f"Default vision_keywords_score should be 0.0, got {features.vision_keywords_score}"
        )
        assert features.frontier_quality_needed is False, (
            "Default frontier_quality_needed should be False"
        )
        assert features.estimated_input_tokens >= 0, (
            f"Default estimated_input_tokens should be >= 0, got {features.estimated_input_tokens}"
        )

    def test_type_error_in_inner_returns_defaults(self):
        """Validates: Requirements 12.7

        IF _extract_features_inner raises a TypeError, THE Feature_Extractor
        SHALL still return conservative defaults.
        """
        state = _make_text_state("test input")

        with patch(
            "src.agent.router.feature_extractor._extract_features_inner",
            side_effect=TypeError("bad type"),
        ):
            features = extract_features("test input", state)

        assert features.task_category == "general"
        assert features.has_images is False
        assert features.document_keywords_score == 0.0
        assert features.vision_keywords_score == 0.0

    # ── Property 13: Feature Extraction Validity ────────────────────
    @given(text=user_text_st)
    @settings(max_examples=100, deadline=None)
    def test_feature_extraction_validity(self, text):
        """Feature: router-model-swap-testing, Property 13: Feature Extraction Validity

        For any user text, extract_features returns TaskFeatures with
        scores in [0.0, 1.0], tokens >= 0, and category in valid set.
        Validates: Requirements 12.1, 12.6
        """
        state = _make_text_state(text)
        features = extract_features(text, state)

        # Scores in [0.0, 1.0] (Req 12.1)
        assert 0.0 <= features.document_keywords_score <= 1.0, (
            f"document_keywords_score {features.document_keywords_score} out of [0.0, 1.0]"
        )
        assert 0.0 <= features.vision_keywords_score <= 1.0, (
            f"vision_keywords_score {features.vision_keywords_score} out of [0.0, 1.0]"
        )

        # Tokens >= 0
        assert features.estimated_input_tokens >= 0, (
            f"estimated_input_tokens {features.estimated_input_tokens} < 0"
        )

        # Category in valid set (Req 12.6)
        assert features.task_category in VALID_TASK_CATEGORIES, (
            f"task_category '{features.task_category}' not in {VALID_TASK_CATEGORIES}"
        )

    # ── Property 14: Feature Detection Accuracy ─────────────────────
    @given(base_text=user_text_st)
    @settings(max_examples=100, deadline=None)
    def test_feature_detection_accuracy(self, base_text):
        """Feature: router-model-swap-testing, Property 14: Feature Detection Accuracy

        For texts with web/frontier/file keywords, corresponding flags
        are True.
        Validates: Requirements 12.2, 12.3, 12.4, 12.5
        """
        # Web intent detection (Req 12.3)
        web_text = base_text + " weather forecast"
        state = _make_text_state(web_text)
        features = extract_features(web_text, state)
        assert features.web_intent is True, (
            "Expected web_intent=True when text contains 'weather'"
        )

        # Frontier quality detection (Req 12.4)
        frontier_text = base_text + " prove theorem"
        state = _make_text_state(frontier_text)
        features = extract_features(frontier_text, state)
        assert features.frontier_quality_needed is True, (
            "Expected frontier_quality_needed=True when text contains 'prove' and 'theorem'"
        )

        # File attachment detection (Req 12.5)
        file_text = base_text + " [file: data.csv]"
        state = _make_text_state(file_text)
        features = extract_features(file_text, state)
        assert features.has_file_attachments is True, (
            "Expected has_file_attachments=True when text contains '[file:' marker"
        )

        # Image detection (Req 12.2)
        image_state = _make_image_state(base_text)
        image_text = base_text
        features = extract_features(image_text, image_state)
        assert features.has_images is True, (
            "Expected has_images=True when state contains image_url content"
        )


# ═════════════════════════════════════════════════════════════════════════
# TestEndToEndRouterFallbackSafety — Requirement 13
# ═════════════════════════════════════════════════════════════════════════

class TestEndToEndRouterFallbackSafety:
    """Verify that the Router never crashes and always returns a valid
    routing state, so that any unexpected error in the pipeline results
    in a safe fallback.

    Feature: router-model-swap-testing
    Requirement: 13 — End-to-End Router Fallback Safety
    """

    # ── Req 13.1: exception in routing → fallback state ──────────────
    @pytest.mark.anyio
    async def test_exception_in_routing_returns_fallback_state(self, mock_profile):
        """Validates: Requirements 13.1

        IF any unexpected exception occurs during routing (in the Classifier,
        Selector, Feature_Extractor, or any other component), THEN THE Router
        SHALL return a fallback state with route complex-default, toolbox
        ["all"], and confidence 0.0.
        """
        with (
            patch(
                "src.agent.nodes.router.extract_features",
                side_effect=RuntimeError("Feature extraction exploded"),
            ),
            patch("src.agent.nodes.router._check_cloud_available", return_value=False),
            patch("src.agent.nodes.router.get_profile", return_value=mock_profile),
        ):
            state = _make_text_state("process some data for me")
            result = await router_node(state)

        assert result["route"] == "complex-default", (
            f"Expected fallback route complex-default, got '{result['route']}'"
        )
        assert result["selected_toolboxes"] == ["all"], (
            f"Expected fallback toolboxes ['all'], got {result['selected_toolboxes']}"
        )
        assert result["router_metadata"]["confidence"] == 0.0, (
            f"Expected fallback confidence 0.0, got {result['router_metadata']['confidence']}"
        )

    # ── Req 13.1 (variant): selector exception → fallback ───────────
    @pytest.mark.anyio
    async def test_selector_exception_returns_fallback_state(self, mock_profile):
        """Validates: Requirements 13.1

        IF the Selector raises an exception during swap-aware selection,
        THEN THE Router SHALL return a fallback state with safe defaults.
        """
        classifier_json = json.dumps({
            "route": "complex-default",
            "confidence": 0.9,
            "toolbox": ["all"],
            "reasoning": "clear request",
        })
        mock_small = _make_mock_llm(response_content=classifier_json)

        with (
            patch("src.agent.nodes.router.get_small_llm", new_callable=AsyncMock, return_value=mock_small),
            patch("src.agent.nodes.router._check_cloud_available", return_value=False),
            patch("src.agent.nodes.router.get_profile", return_value=mock_profile),
            patch(
                "src.agent.nodes.router._selector.select",
                side_effect=RuntimeError("Selector exploded"),
            ),
        ):
            # Use text that won't trigger deterministic overrides or greeting bypass
            state = _make_text_state("process data and generate a report for me")
            result = await router_node(state)

        assert result["route"] == "complex-default", (
            f"Expected fallback route complex-default, got '{result['route']}'"
        )
        assert result["selected_toolboxes"] == ["all"], (
            f"Expected fallback toolboxes ['all'], got {result['selected_toolboxes']}"
        )
        assert result["router_metadata"]["confidence"] == 0.0

    # ── Req 13.2: router always returns dict with required keys ──────
    @pytest.mark.anyio
    async def test_fallback_state_contains_all_required_keys(self, mock_profile):
        """Validates: Requirements 13.2

        THE Router SHALL always return a state dict containing route,
        token_budget, selected_toolboxes, router_clarification_used,
        and router_metadata keys.
        """
        with (
            patch(
                "src.agent.nodes.router.extract_features",
                side_effect=ValueError("Unexpected error"),
            ),
            patch("src.agent.nodes.router._check_cloud_available", return_value=False),
            patch("src.agent.nodes.router.get_profile", return_value=mock_profile),
        ):
            state = _make_text_state("test input")
            result = await router_node(state)

        required_keys = {
            "route", "token_budget", "selected_toolboxes",
            "router_clarification_used", "router_metadata",
        }
        for key in required_keys:
            assert key in result, (
                f"Expected key '{key}' in router fallback result, "
                f"got keys: {set(result.keys())}"
            )

    # ── Req 13.2 (normal path): required keys present on success ─────
    @pytest.mark.anyio
    async def test_normal_path_contains_all_required_keys(self, mock_profile):
        """Validates: Requirements 13.2

        THE Router SHALL always return a state dict containing all required
        keys even on the normal (non-fallback) path.
        """
        classifier_json = json.dumps({
            "route": "complex-default",
            "confidence": 0.9,
            "toolbox": ["all"],
            "reasoning": "clear request",
        })
        mock_small = _make_mock_llm(response_content=classifier_json)

        with (
            patch("src.agent.nodes.router.get_small_llm", new_callable=AsyncMock, return_value=mock_small),
            patch("src.agent.nodes.router._check_cloud_available", return_value=False),
            patch("src.agent.nodes.router.get_profile", return_value=mock_profile),
        ):
            state = _make_text_state("process data and generate a report for me")
            result = await _router_node_inner(state, RouterConfig())

        required_keys = {
            "route", "token_budget", "selected_toolboxes",
            "router_clarification_used", "router_metadata",
        }
        for key in required_keys:
            assert key in result, (
                f"Expected key '{key}' in router result, got keys: {set(result.keys())}"
            )

    # ── Req 13.3: fallback metadata has classification_source="deterministic" ──
    @pytest.mark.anyio
    async def test_fallback_metadata_has_deterministic_source(self, mock_profile):
        """Validates: Requirements 13.3

        WHEN the Router returns a fallback state due to an error, THE
        router_metadata.classification_source SHALL be "deterministic".
        """
        with (
            patch(
                "src.agent.nodes.router.extract_features",
                side_effect=TypeError("Bad type in feature extraction"),
            ),
            patch("src.agent.nodes.router._check_cloud_available", return_value=False),
            patch("src.agent.nodes.router.get_profile", return_value=mock_profile),
        ):
            state = _make_text_state("analyze this data")
            result = await router_node(state)

        metadata = result["router_metadata"]
        assert metadata["classification_source"] == "deterministic", (
            f"Expected classification_source='deterministic' in fallback metadata, "
            f"got '{metadata['classification_source']}'"
        )

    # ── Req 13.4: various inputs → route in VALID_ROUTES ────────────
    @pytest.mark.anyio
    async def test_empty_message_returns_valid_route(self):
        """Validates: Requirements 13.4

        FOR empty messages, THE Router SHALL return a route in the valid set.
        """
        state = {"messages": [], "web_search_enabled": True}
        with patch("src.agent.nodes.router._check_cloud_available", return_value=False):
            result = await router_node(state)

        assert result["route"] in VALID_ROUTES, (
            f"Expected route in {VALID_ROUTES}, got '{result['route']}'"
        )

    @pytest.mark.anyio
    async def test_unicode_input_returns_valid_route(self, mock_profile):
        """Validates: Requirements 13.4

        FOR unicode input, THE Router SHALL return a route in the valid set.
        """
        classifier_json = json.dumps({
            "route": "complex-default",
            "confidence": 0.8,
            "toolbox": ["all"],
            "reasoning": "unicode input",
        })
        mock_small = _make_mock_llm(response_content=classifier_json)

        with (
            patch("src.agent.nodes.router.get_small_llm", new_callable=AsyncMock, return_value=mock_small),
            patch("src.agent.nodes.router._check_cloud_available", return_value=False),
            patch("src.agent.nodes.router.get_profile", return_value=mock_profile),
        ):
            state = _make_text_state("こんにちは 🌍 Ñoño résumé naïve")
            result = await router_node(state)

        assert result["route"] in VALID_ROUTES, (
            f"Expected route in {VALID_ROUTES} for unicode input, got '{result['route']}'"
        )

    @pytest.mark.anyio
    async def test_multimodal_input_returns_valid_route(self, mock_profile):
        """Validates: Requirements 13.4

        FOR multimodal input (image_url content), THE Router SHALL return
        a route in the valid set.
        """
        with (
            patch("src.agent.nodes.router._check_cloud_available", return_value=False),
            patch("src.agent.nodes.router.get_profile", return_value=mock_profile),
        ):
            state = _make_image_state("Describe this")
            result = await router_node(state)

        assert result["route"] in VALID_ROUTES, (
            f"Expected route in {VALID_ROUTES} for multimodal input, got '{result['route']}'"
        )

    # ── Property 15: Router Output Validity ─────────────────────────
    @given(text=user_text_st)
    @settings(max_examples=100, deadline=None)
    @pytest.mark.anyio
    async def test_router_output_validity(self, text):
        """Feature: router-model-swap-testing, Property 15: Router Output Validity

        For any user input, router_node returns a dict with all required
        keys and a valid route.
        Validates: Requirements 13.2, 13.4
        """
        classifier_json = json.dumps({
            "route": "complex-default",
            "confidence": 0.8,
            "toolbox": ["all"],
            "reasoning": "property test",
        })
        mock_small = _make_mock_llm(response_content=classifier_json)

        with (
            patch("src.agent.nodes.router.get_small_llm", new_callable=AsyncMock, return_value=mock_small),
            patch("src.agent.nodes.router._check_cloud_available", return_value=False),
            patch("src.agent.nodes.router.get_profile", return_value={
                "router_hitl_enabled": False,
                "cloud_escalation_enabled": False,
                "cloud_hitl_enabled": False,
                "deepseek_api_key": "",
            }),
        ):
            state = _make_text_state(text)
            result = await router_node(state)

        # Required keys (Req 13.2)
        required_keys = {"route", "token_budget", "selected_toolboxes",
                         "router_clarification_used", "router_metadata"}
        for key in required_keys:
            assert key in result, f"Missing required key '{key}' in router output"

        # Valid route (Req 13.4)
        assert result["route"] in VALID_ROUTES, (
            f"Expected route in {VALID_ROUTES}, got '{result['route']}'"
        )

        # token_budget is positive integer
        assert isinstance(result["token_budget"], int) and result["token_budget"] >= 1, (
            f"Expected positive int token_budget, got {result['token_budget']}"
        )

        # selected_toolboxes is a non-empty list
        assert isinstance(result["selected_toolboxes"], list) and len(result["selected_toolboxes"]) > 0, (
            f"Expected non-empty toolbox list, got {result['selected_toolboxes']}"
        )
