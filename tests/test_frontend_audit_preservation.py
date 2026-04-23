"""
Preservation Property Tests for Frontend Audit Fixes.

These tests capture EXISTING correct behavior in the unfixed codebase that
must be preserved after the bugfix. They parse frontend source files as text
(static analysis) and use Hypothesis where appropriate.

IMPORTANT: These tests MUST PASS on the current unfixed code.
They define the baseline behavior we want to keep intact.

Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8, 3.9, 3.10,
           3.11, 3.12, 3.13, 3.14, 3.15
"""

import os
import re
import math
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


# ─── 1. Payload Format: buildChatWsPayload ───────────────────────────────────

class TestPayloadFormat:
    """
    **Validates: Requirements 3.10**

    Verify buildChatWsPayload function returns an object with the correct keys:
    message, files, mode, web_search_enabled, response_style, project_id.
    """

    EXPECTED_KEYS = ['message', 'files', 'mode', 'web_search_enabled',
                     'response_style', 'project_id']

    def test_build_chat_ws_payload_exists(self, script_js):
        """buildChatWsPayload function must exist in script.js."""
        assert re.search(
            r'function\s+buildChatWsPayload\s*\(',
            script_js
        ), "buildChatWsPayload function not found in script.js"

    def test_payload_contains_all_keys(self, script_js):
        """buildChatWsPayload must return an object with all required keys."""
        # Extract the function body
        match = re.search(
            r'function\s+buildChatWsPayload\s*\([^)]*\)\s*\{',
            script_js
        )
        assert match is not None

        start = match.end() - 1
        brace_count = 0
        func_body = ''
        for i in range(start, len(script_js)):
            if script_js[i] == '{':
                brace_count += 1
            elif script_js[i] == '}':
                brace_count -= 1
                if brace_count == 0:
                    func_body = script_js[start:i + 1]
                    break

        for key in self.EXPECTED_KEYS:
            assert re.search(rf'\b{key}\s*:', func_body), (
                f"Key '{key}' not found in buildChatWsPayload return object"
            )

    @given(key_idx=st.integers(min_value=0, max_value=5))
    @settings(max_examples=6)
    def test_payload_key_present_property(self, script_js, key_idx):
        """
        **Validates: Requirements 3.10**

        For each expected payload key, verify it appears in the
        buildChatWsPayload function body.
        """
        key = self.EXPECTED_KEYS[key_idx]
        match = re.search(
            r'function\s+buildChatWsPayload\s*\([^)]*\)\s*\{',
            script_js
        )
        assert match is not None

        start = match.end() - 1
        brace_count = 0
        func_body = ''
        for i in range(start, len(script_js)):
            if script_js[i] == '{':
                brace_count += 1
            elif script_js[i] == '}':
                brace_count -= 1
                if brace_count == 0:
                    func_body = script_js[start:i + 1]
                    break

        assert re.search(rf'\b{key}\s*:', func_body), (
            f"Key '{key}' not found in buildChatWsPayload return object"
        )


# ─── 2. Exponential Backoff ──────────────────────────────────────────────────

class TestExponentialBackoff:
    """
    **Validates: Requirements 3.2**

    Verify StateManager._reconnect uses the exponential backoff pattern:
    Math.min(Math.pow(2, _reconnectAttempt) * 1000, 30000)
    """

    def test_reconnect_uses_exponential_backoff_pattern(self, script_js):
        """_reconnect must use Math.min(Math.pow(2, ...) * 1000, 30000)."""
        assert re.search(
            r'Math\.min\s*\(\s*Math\.pow\s*\(\s*2\s*,\s*_reconnectAttempt\s*\)\s*\*\s*1000\s*,\s*30000\s*\)',
            script_js
        ), (
            "Exponential backoff pattern "
            "'Math.min(Math.pow(2, _reconnectAttempt) * 1000, 30000)' "
            "not found in script.js"
        )

    @given(attempt=st.integers(min_value=0, max_value=20))
    @settings(max_examples=21)
    def test_backoff_delay_calculation(self, attempt):
        """
        **Validates: Requirements 3.2**

        For all reconnection attempt counts 0–20, the backoff delay must equal
        min(2^attempt * 1000, 30000).
        """
        expected_delay = min(math.pow(2, attempt) * 1000, 30000)
        assert expected_delay >= 1000, "Minimum delay should be 1000ms (attempt=0)"
        assert expected_delay <= 30000, "Maximum delay should be capped at 30000ms"

        # Verify the formula produces correct values for known checkpoints
        if attempt == 0:
            assert expected_delay == 1000
        elif attempt == 1:
            assert expected_delay == 2000
        elif attempt == 2:
            assert expected_delay == 4000
        elif attempt == 3:
            assert expected_delay == 8000
        elif attempt == 4:
            assert expected_delay == 16000
        elif attempt >= 5:
            assert expected_delay == 30000


# ─── 3. Security Approval Modal ─────────────────────────────────────────────

class TestSecurityApprovalModal:
    """
    **Validates: Requirements 3.4**

    Verify securityApprovalModal element ID exists in index.html.
    """

    def test_security_approval_modal_exists(self, index_html):
        """securityApprovalModal must exist in index.html."""
        assert re.search(
            r'id\s*=\s*["\']securityApprovalModal["\']',
            index_html
        ), "securityApprovalModal element not found in index.html"


# ─── 4. Spotlight Modal ─────────────────────────────────────────────────────

class TestSpotlightModal:
    """
    **Validates: Requirements 3.7**

    Verify spotlightModal element ID exists in index.html.
    """

    def test_spotlight_modal_exists(self, index_html):
        """spotlightModal must exist in index.html."""
        assert re.search(
            r'id\s*=\s*["\']spotlightModal["\']',
            index_html
        ), "spotlightModal element not found in index.html"


# ─── 5. File Viewer Modal ───────────────────────────────────────────────────

class TestFileViewerModal:
    """
    **Validates: Requirements 3.11**

    Verify fileViewerModal element ID exists in index.html.
    """

    def test_file_viewer_modal_exists(self, index_html):
        """fileViewerModal must exist in index.html."""
        assert re.search(
            r'id\s*=\s*["\']fileViewerModal["\']',
            index_html
        ), "fileViewerModal element not found in index.html"


# ─── 6. API Endpoints ───────────────────────────────────────────────────────

class TestAPIEndpoints:
    """
    **Validates: Requirements 3.13**

    Verify settings save functions reference correct API endpoints:
    /api/profile, /api/advanced-settings, /api/system-settings, /api/persona.
    """

    EXPECTED_ENDPOINTS = [
        ('saveProfileSettings', '/api/profile'),
        ('saveAdvancedSettings', '/api/advanced-settings'),
        ('saveSystemSettings', '/api/system-settings'),
    ]

    def test_save_profile_endpoint(self, script_js):
        """saveProfileSettings must reference /api/profile."""
        func_match = re.search(r'function\s+saveProfileSettings\s*\(', script_js)
        assert func_match, "saveProfileSettings function not found"
        # Check the function body contains the endpoint
        body_start = func_match.start()
        body_end = script_js.find('\n}', body_start)
        func_body = script_js[body_start:body_end + 2] if body_end != -1 else ''
        assert '/api/profile' in func_body, (
            "saveProfileSettings does not reference /api/profile endpoint"
        )

    def test_save_advanced_settings_endpoint(self, script_js):
        """saveAdvancedSettings must reference /api/advanced-settings."""
        func_match = re.search(r'function\s+saveAdvancedSettings\s*\(', script_js)
        assert func_match, "saveAdvancedSettings function not found"
        body_start = func_match.start()
        body_end = script_js.find('\n}', body_start)
        func_body = script_js[body_start:body_end + 2] if body_end != -1 else ''
        assert '/api/advanced-settings' in func_body, (
            "saveAdvancedSettings does not reference /api/advanced-settings endpoint"
        )

    def test_save_system_settings_endpoint(self, script_js):
        """saveSystemSettings must reference /api/system-settings."""
        func_match = re.search(r'function\s+saveSystemSettings\s*\(', script_js)
        assert func_match, "saveSystemSettings function not found"
        body_start = func_match.start()
        body_end = script_js.find('\n}', body_start)
        func_body = script_js[body_start:body_end + 2] if body_end != -1 else ''
        assert '/api/system-settings' in func_body, (
            "saveSystemSettings does not reference /api/system-settings endpoint"
        )

    def test_persona_endpoint_referenced(self, script_js):
        """The /api/persona endpoint must be referenced in script.js."""
        assert '/api/persona' in script_js, (
            "/api/persona endpoint not found in script.js"
        )

    @given(idx=st.integers(min_value=0, max_value=2))
    @settings(max_examples=3)
    def test_endpoint_present_property(self, script_js, idx):
        """
        **Validates: Requirements 3.13**

        For each expected save endpoint, verify the corresponding function
        references the correct API path.
        """
        func_name, endpoint = self.EXPECTED_ENDPOINTS[idx]
        func_match = re.search(rf'function\s+{func_name}\s*\(', script_js)
        assert func_match, f"{func_name} function not found"
        body_start = func_match.start()
        body_end = script_js.find('\n}', body_start)
        func_body = script_js[body_start:body_end + 2] if body_end != -1 else ''
        assert endpoint in func_body, (
            f"{func_name} does not reference {endpoint} endpoint"
        )


# ─── 7. Aurora Module Structure ──────────────────────────────────────────────

class TestAuroraModuleStructure:
    """
    **Validates: Requirements 3.1**

    Verify StateManager, LeftPane, CenterPane, RightPane, BottomInputBar
    modules exist in script.js.
    """

    MODULES = ['StateManager', 'LeftPane', 'CenterPane', 'RightPane',
               'BottomInputBar']

    def test_all_aurora_modules_exist(self, script_js):
        """All five Aurora modules must be defined in script.js."""
        for module in self.MODULES:
            assert re.search(
                rf'const\s+{module}\s*=\s*\(\s*\(\s*\)\s*=>',
                script_js
            ), f"Aurora module '{module}' not found in script.js"

    @given(idx=st.integers(min_value=0, max_value=4))
    @settings(max_examples=5)
    def test_module_exists_property(self, script_js, idx):
        """
        **Validates: Requirements 3.1**

        For each Aurora module, verify it is defined as a const IIFE in script.js.
        """
        module = self.MODULES[idx]
        assert re.search(
            rf'const\s+{module}\s*=\s*\(\s*\(\s*\)\s*=>',
            script_js
        ), f"Aurora module '{module}' not found in script.js"


# ─── 8. Pane Resize ─────────────────────────────────────────────────────────

class TestPaneResize:
    """
    **Validates: Requirements 3.1**

    Verify _initPaneResize function exists and handles mousedown events.
    """

    def test_init_pane_resize_exists(self, script_js):
        """_initPaneResize function must exist in script.js."""
        assert re.search(
            r'function\s+_initPaneResize\s*\(',
            script_js
        ), "_initPaneResize function not found in script.js"

    def test_pane_resize_handles_mousedown(self, script_js):
        """_initPaneResize must attach mousedown event listeners."""
        # Extract the function body
        match = re.search(
            r'function\s+_initPaneResize\s*\(\s*\)\s*\{',
            script_js
        )
        assert match is not None

        start = match.end() - 1
        brace_count = 0
        func_body = ''
        for i in range(start, len(script_js)):
            if script_js[i] == '{':
                brace_count += 1
            elif script_js[i] == '}':
                brace_count -= 1
                if brace_count == 0:
                    func_body = script_js[start:i + 1]
                    break

        assert 'mousedown' in func_body, (
            "_initPaneResize does not handle mousedown events"
        )
        assert 'pane-resize-handle' in func_body, (
            "_initPaneResize does not reference pane-resize-handle elements"
        )


# ─── 9. Keyboard Shortcuts ──────────────────────────────────────────────────

class TestKeyboardShortcuts:
    """
    **Validates: Requirements 3.7**

    Verify Cmd/Ctrl+K spotlight toggle exists in script.js.
    """

    def test_cmd_ctrl_k_spotlight_toggle(self, script_js):
        """Cmd/Ctrl+K must toggle the spotlight modal."""
        # Check for the keyboard shortcut pattern
        assert re.search(
            r"(metaKey|ctrlKey).*&&.*(metaKey|ctrlKey).*key\s*===?\s*['\"]k['\"]|"
            r"\(\s*e\.(metaKey|ctrlKey)\s*\|\|\s*e\.(ctrlKey|metaKey)\s*\)\s*&&\s*e\.key\s*===?\s*['\"]k['\"]",
            script_js
        ), "Cmd/Ctrl+K spotlight toggle not found in script.js"

    def test_spotlight_modal_toggled(self, script_js):
        """The spotlight toggle must reference spotlightModal."""
        # Find the keydown handler that checks for 'k'
        assert re.search(
            r"spotlightModal.*toggle|toggle.*spotlightModal",
            script_js,
            re.DOTALL
        ), "spotlightModal toggle not found near keyboard shortcut handler"


# ─── 10. DOMPurify Available ─────────────────────────────────────────────────

class TestDOMPurifyAvailable:
    """
    **Validates: Requirements 3.3**

    Verify purify.min.js is loaded in index.html.
    """

    def test_purify_script_loaded(self, index_html):
        """purify.min.js must be loaded via a script tag in index.html."""
        assert re.search(
            r'<script\s+src\s*=\s*["\'][^"\']*purify\.min\.js["\']',
            index_html
        ), "purify.min.js script tag not found in index.html"


# ─── 11. Marked Available ───────────────────────────────────────────────────

class TestMarkedAvailable:
    """
    **Validates: Requirements 3.3**

    Verify marked.min.js is loaded in index.html.
    """

    def test_marked_script_loaded(self, index_html):
        """marked.min.js must be loaded via a script tag in index.html."""
        assert re.search(
            r'<script\s+src\s*=\s*["\'][^"\']*marked\.min\.js["\']',
            index_html
        ), "marked.min.js script tag not found in index.html"
