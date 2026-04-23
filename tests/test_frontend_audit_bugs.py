"""
Bug Condition Exploration Tests for Frontend Audit Fixes.

These tests encode the EXPECTED (fixed) behavior for 15 bugs found in the
Owlynn AI frontend. They parse the frontend source files as text and check
for the bug conditions.

CRITICAL: These tests MUST FAIL on the current unfixed code.
Failure confirms the bugs exist. Do NOT fix the code or the tests when they fail.

Validates: Requirements 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 1.8, 1.9, 1.10,
           1.11, 1.12, 1.13, 1.14, 1.15
"""

import os
import re
import pytest
from hypothesis import given, settings, assume
from hypothesis import strategies as st

# ─── Fixtures ────────────────────────────────────────────────────────────────

FRONTEND_DIR = os.path.join(os.path.dirname(__file__), '..', 'frontend')


@pytest.fixture(scope='session')
def script_js():
    """Load frontend/script.js as text."""
    path = os.path.join(FRONTEND_DIR, 'script.js')
    with open(path, 'r', encoding='utf-8') as f:
        return f.read()


@pytest.fixture(scope='session')
def index_html():
    """Load frontend/index.html as text."""
    path = os.path.join(FRONTEND_DIR, 'index.html')
    with open(path, 'r', encoding='utf-8') as f:
        return f.read()


@pytest.fixture(scope='session')
def style_css():
    """Load frontend/style.css as text."""
    path = os.path.join(FRONTEND_DIR, 'style.css')
    with open(path, 'r', encoding='utf-8') as f:
        return f.read()


# ─── Bug 1 & 12: Dual WebSocket — Two connectWebSocket call paths ───────────

class TestDualWebSocket:
    """
    **Validates: Requirements 1.1, 1.12**

    Verify that script.js has only ONE connectWebSocket call path during
    initialization. The unfixed code has TWO: a legacy call at parse time
    (line ~1801) and an Aurora call in initAuroraLayout via
    StateManager.connectWebSocket.
    """

    def test_single_websocket_init_path(self, script_js):
        """There should be only ONE connectWebSocket initialization path.

        The unfixed code has a bare `connectWebSocket();` call at parse time
        (legacy) AND `StateManager.connectWebSocket(...)` in initAuroraLayout.
        The fixed code should only have the StateManager path.
        """
        # Find bare legacy connectWebSocket() calls at top-level (not inside a function def)
        # The legacy call is a standalone `connectWebSocket();` at module scope
        legacy_calls = re.findall(
            r'^connectWebSocket\(\);',
            script_js,
            re.MULTILINE
        )
        assert len(legacy_calls) == 0, (
            f"Found {len(legacy_calls)} legacy top-level connectWebSocket() call(s). "
            "Expected 0 — only StateManager.connectWebSocket() should exist."
        )

    def test_no_legacy_connectWebSocket_function(self, script_js):
        """The legacy global connectWebSocket function (flat 3s retry) should not exist."""
        # The legacy function is defined as `function connectWebSocket() {`
        legacy_func = re.findall(
            r'^function\s+connectWebSocket\s*\(',
            script_js,
            re.MULTILINE
        )
        assert len(legacy_func) == 0, (
            f"Found {len(legacy_func)} legacy connectWebSocket function definition(s). "
            "Expected 0 — only StateManager.connectWebSocket() should exist."
        )


# ─── Bug 2: Dead DOM References ─────────────────────────────────────────────

class TestDeadDOMReferences:
    """
    **Validates: Requirements 1.1, 1.10, 1.14**

    Parse script.js for getElementById calls and cross-reference against
    index.html. Verify zero references to non-existent elements.
    """

    # Elements that do NOT exist in the Aurora index.html
    DEAD_ELEMENT_IDS = [
        'chatForm',
        'view-welcome',
        'newChatBtn',
        'connectionStatusDot',
        'connectionStatusText',
        'mobileConnectionDot',
        'agentStatus',
        'fileViewerContent',
        'downloadFileBtn',
        'openSettingsBtn',
        'closeSettingsBtn',
        'closeSettingsFooterBtn',
        'profileName',
        'profileLang',
        'profileStyle',
        'profileLlmUrl',
        'profileLlmModel',
        'saveProfileBtn',
        'personaName',
        'personaTone',
        'savePersonaBtn',
        'agentNameDisplay',
        'agentRoleDisplay',
        'memoriesCount',
        'newMemoryInput',
        'addMemoryBtn',
        'memoriesList',
        'modeFastBtn',
        'modeReasoningBtn',
        'projectsList',
        'addProjectBtn',
        'projectKnowledgeSection',
        'projectFilesList',
        'sidebarRecentsList',
        'welcomeAttachmentPreviews',
        'attachBtn',
        'sessionId',
    ]

    @given(idx=st.integers(min_value=0, max_value=len(DEAD_ELEMENT_IDS) - 1))
    @settings(max_examples=len(DEAD_ELEMENT_IDS))
    def test_no_dead_dom_references(self, script_js, idx):
        """
        **Validates: Requirements 1.1, 1.10, 1.14**

        For each known dead element ID, verify script.js does not reference it
        via getElementById.
        """
        element_id = self.DEAD_ELEMENT_IDS[idx]
        # Match getElementById('elementId') or getElementById("elementId")
        pattern = rf"""getElementById\s*\(\s*['"]{ re.escape(element_id) }['"]\s*\)"""
        matches = re.findall(pattern, script_js)
        assert len(matches) == 0, (
            f"Found {len(matches)} reference(s) to non-existent element "
            f"'{element_id}' via getElementById in script.js. Expected 0."
        )


# ─── Bug 3: XSS Sanitization ────────────────────────────────────────────────

class TestXSSSanitization:
    """
    **Validates: Requirements 1.3**

    Verify that ALL marked.parse() calls in script.js are wrapped with
    DOMPurify.sanitize().
    """

    def test_all_marked_parse_sanitized(self, script_js):
        """Every marked.parse() call assigned to innerHTML must be wrapped
        with DOMPurify.sanitize()."""
        # Find all marked.parse() calls
        all_marked_parse = re.findall(r'marked\.parse\(', script_js)

        # Find marked.parse() calls that ARE wrapped with DOMPurify.sanitize()
        sanitized_calls = re.findall(
            r'DOMPurify\.sanitize\s*\(\s*marked\.parse\(',
            script_js
        )

        assert len(all_marked_parse) == len(sanitized_calls), (
            f"Found {len(all_marked_parse)} marked.parse() calls but only "
            f"{len(sanitized_calls)} are wrapped with DOMPurify.sanitize(). "
            f"All {len(all_marked_parse)} must be sanitized."
        )

    @given(payload=st.sampled_from([
        '<script>alert(1)</script>',
        '<img src=x onerror=alert(1)>',
        '<div onclick=alert(1)>click</div>',
        '<svg onload=alert(1)>',
        '<iframe src="javascript:alert(1)">',
    ]))
    @settings(max_examples=5)
    def test_xss_patterns_require_sanitization(self, script_js, payload):
        """
        **Validates: Requirements 1.3**

        For various XSS payloads, the rendering pipeline must sanitize
        marked.parse() output. We verify the source code pattern exists.
        """
        # This is a static check — we verify the sanitization pattern exists
        # in the source code for the main rendering path (handleChunk)
        # Find innerHTML assignments using marked.parse without DOMPurify
        unsanitized = re.findall(
            r'\.innerHTML\s*=\s*marked\.parse\(',
            script_js
        )
        assert len(unsanitized) == 0, (
            f"Found {len(unsanitized)} innerHTML assignment(s) using "
            f"marked.parse() without DOMPurify.sanitize() wrapping. "
            f"XSS payload '{payload}' would not be sanitized."
        )


# ─── Bug 4: Missing Modals ──────────────────────────────────────────────────

class TestMissingModals:
    """
    **Validates: Requirements 1.4**

    Verify customConfirmModal and customInputModal exist in index.html.
    """

    def test_custom_confirm_modal_exists(self, index_html):
        """customConfirmModal must exist in index.html."""
        assert 'customConfirmModal' in index_html, (
            "customConfirmModal element not found in index.html. "
            "showCustomConfirm() will fall back to native window.confirm()."
        )

    def test_custom_input_modal_exists(self, index_html):
        """customInputModal must exist in index.html."""
        assert 'customInputModal' in index_html, (
            "customInputModal element not found in index.html. "
            "showCustomInput() will fall back to native window.prompt()."
        )


# ─── Bug 5: Inline onclick in handleAskUserInterrupt ────────────────────────

class TestInlineOnclick:
    """
    **Validates: Requirements 1.5**

    Verify handleAskUserInterrupt does NOT contain onclick= attribute strings.
    """

    def test_no_inline_onclick_in_ask_user(self, script_js):
        """handleAskUserInterrupt should use addEventListener, not onclick=."""
        # Extract the handleAskUserInterrupt function body
        match = re.search(
            r'function\s+handleAskUserInterrupt\s*\([^)]*\)\s*\{',
            script_js
        )
        assert match is not None, "handleAskUserInterrupt function not found"

        # Get function body (find matching closing brace)
        start = match.start()
        brace_count = 0
        func_body = ''
        for i in range(match.end() - 1, len(script_js)):
            char = script_js[i]
            if char == '{':
                brace_count += 1
            elif char == '}':
                brace_count -= 1
                if brace_count == 0:
                    func_body = script_js[start:i + 1]
                    break

        assert 'onclick=' not in func_body, (
            "handleAskUserInterrupt contains inline onclick= attributes. "
            "Should use addEventListener instead for safe handling of "
            "special characters in choice text."
        )


# ─── Bug 6 (11): File Viewer Wrong ID ───────────────────────────────────────

class TestFileViewerWrongID:
    """
    **Validates: Requirements 1.11**

    Verify viewWorkspaceFile references fileViewerBody (not fileViewerContent).
    """

    def test_file_viewer_uses_correct_id(self, script_js):
        """viewWorkspaceFile should reference fileViewerBody, not fileViewerContent."""
        # Extract viewWorkspaceFile function
        match = re.search(
            r'(?:async\s+)?function\s+viewWorkspaceFile\s*\(',
            script_js
        )
        assert match is not None, "viewWorkspaceFile function not found"

        start = match.start()
        brace_count = 0
        func_body = ''
        for i in range(match.end(), len(script_js)):
            char = script_js[i]
            if char == '{':
                brace_count += 1
            elif char == '}':
                brace_count -= 1
                if brace_count == 0:
                    func_body = script_js[start:i + 1]
                    break

        assert 'fileViewerContent' not in func_body, (
            "viewWorkspaceFile references 'fileViewerContent' which does not "
            "exist in index.html. Should reference 'fileViewerBody' instead."
        )

        assert 'fileViewerBody' in func_body, (
            "viewWorkspaceFile does not reference 'fileViewerBody'. "
            "The function should use the correct element ID."
        )


# ─── Bug 7 (15): Status Dot Conflict ────────────────────────────────────────

class TestStatusDotConflict:
    """
    **Validates: Requirements 1.15**

    Verify no function in script.js sets statusDot.className to Tailwind
    utility classes (bg-green-500, bg-yellow-500, bg-red-500).
    """

    @given(tw_class=st.sampled_from(['bg-green-500', 'bg-yellow-500', 'bg-red-500']))
    @settings(max_examples=3)
    def test_no_tailwind_status_dot_classes(self, script_js, tw_class):
        """
        **Validates: Requirements 1.15**

        statusDot.className should never be set to Tailwind utility classes.
        Only aurora-dot classes should be used.
        """
        pattern = rf"statusDot\.className\s*=\s*'[^']*{re.escape(tw_class)}[^']*'"
        matches = re.findall(pattern, script_js)
        assert len(matches) == 0, (
            f"Found {len(matches)} assignment(s) of statusDot.className "
            f"containing Tailwind class '{tw_class}'. Should use aurora-dot "
            f"classes instead."
        )


# ─── Bug 8: Pruned Message Restoration ──────────────────────────────────────

class TestPrunedMessageRestoration:
    """
    **Validates: Requirements 1.6**

    Verify a scroll event listener exists that calls restorePrunedMessages.
    """

    def test_scroll_listener_restores_pruned(self, script_js):
        """A scroll event listener should call restorePrunedMessages."""
        # Check for scroll event listener that references restorePrunedMessages
        has_scroll_restore = bool(re.search(
            r'scroll.*restorePrunedMessages|restorePrunedMessages.*scroll|'
            r"addEventListener\s*\(\s*['\"]scroll['\"].*restorePruned",
            script_js,
            re.DOTALL
        ))
        assert has_scroll_restore, (
            "No scroll event listener found that calls restorePrunedMessages. "
            "Pruned messages are permanently hidden with no way to restore them."
        )


# ─── Bug 9: Title Bar Drag Region ───────────────────────────────────────────

class TestTitleBarDrag:
    """
    **Validates: Requirements 1.7**

    Verify CSS has proper drag region setup — title-spacer should NOT have
    no-drag, ensuring there's a reliable drag surface.
    """

    def test_title_spacer_not_no_drag(self, style_css):
        """title-spacer should not have -webkit-app-region: no-drag."""
        # Check if title-spacer rule contains no-drag
        spacer_match = re.search(
            r'\.title-spacer\s*\{[^}]*\}',
            style_css,
            re.DOTALL
        )
        if spacer_match:
            spacer_rule = spacer_match.group(0)
            assert 'no-drag' not in spacer_rule, (
                "title-spacer has -webkit-app-region: no-drag, consuming "
                "drag surface. It should inherit drag from #titleBar."
            )

    def test_titlebar_has_drag(self, style_css):
        """#titleBar must have -webkit-app-region: drag."""
        assert re.search(
            r'#titleBar\s*\{[^}]*-webkit-app-region:\s*drag',
            style_css,
            re.DOTALL
        ), "#titleBar must have -webkit-app-region: drag"

    def test_only_interactive_elements_no_drag(self, style_css):
        """Only buttons, inputs, and links inside #titleBar should be no-drag."""
        # The no-drag rule should target interactive elements
        has_interactive_no_drag = bool(re.search(
            r'#titleBar\s+button.*-webkit-app-region:\s*no-drag|'
            r'#titleBar\s.*button.*\{[^}]*-webkit-app-region:\s*no-drag',
            style_css,
            re.DOTALL
        ))
        assert has_interactive_no_drag, (
            "No CSS rule found that sets -webkit-app-region: no-drag "
            "specifically for interactive elements (button, input, a) "
            "inside #titleBar."
        )


# ─── Bug 10: Settings Modal Content ─────────────────────────────────────────

class TestSettingsModalContent:
    """
    **Validates: Requirements 1.13**

    Verify script.js contains a renderSettingsUI function that populates
    #settingsBody.
    """

    def test_render_settings_ui_exists(self, script_js):
        """A renderSettingsUI function should exist in script.js."""
        has_func = bool(re.search(
            r'function\s+renderSettingsUI|renderSettingsUI\s*[=:]\s*(?:function|\()',
            script_js
        ))
        assert has_func, (
            "renderSettingsUI function not found in script.js. "
            "The settings modal body is empty with no form fields."
        )


# ─── Bug 11: Button Handlers ────────────────────────────────────────────────

class TestButtonHandlers:
    """
    **Validates: Requirements 1.8**

    Verify newTaskBtn and micBtn have event listeners attached.
    """

    def test_new_task_btn_has_handler(self, script_js):
        """newTaskBtn should have an event listener or click handler."""
        has_handler = bool(re.search(
            r"newTaskBtn.*addEventListener|"
            r"getElementById\s*\(\s*['\"]newTaskBtn['\"]\s*\).*addEventListener|"
            r"newTaskBtn.*onclick|"
            r"newTaskBtn.*\.on\(",
            script_js,
            re.DOTALL
        ))
        assert has_handler, (
            "newTaskBtn has no event listener attached. "
            "The 'New Task +' button is non-functional."
        )

    def test_mic_btn_has_handler(self, script_js):
        """micBtn should have an event listener or click handler."""
        has_handler = bool(re.search(
            r"micBtn.*addEventListener|"
            r"getElementById\s*\(\s*['\"]micBtn['\"]\s*\).*addEventListener|"
            r"micBtn.*onclick|"
            r"micBtn.*\.on\(",
            script_js,
            re.DOTALL
        ))
        assert has_handler, (
            "micBtn has no event listener attached. "
            "The Mic button is non-functional."
        )
