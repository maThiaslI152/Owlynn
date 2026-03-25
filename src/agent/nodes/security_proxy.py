"""
Security proxy node for tool execution governance.

This node sits between LLM tool-call planning and actual tool execution.
It enforces policy checks and triggers HITL interruption for sensitive actions.
"""

import json
import re
from typing import Any

from langchain_core.messages import AIMessage
from langgraph.types import interrupt

from src.agent.state import AgentState


SENSITIVE_TOOLS = {
    "execute_sandboxed_shell",
    "execute_python_code",
    "delete_workspace_file",
    "write_workspace_file",
    "edit_workspace_file",
    "create_directory",
}

SENSITIVE_PATTERN_RE = re.compile(
    r"(?:\brm\s+-rf\b|(?:^|[;&|])\s*curl\b|(?:^|[;&|])\s*wget\b|\bsudo\b|\bchmod\b|\bchown\b|\bssh\b|\bscp\b)",
    re.IGNORECASE,
)


def _normalize_approval(decision: Any) -> bool:
    """Normalize resume payload from HITL interrupt into an approval boolean."""
    if isinstance(decision, bool):
        return decision
    if isinstance(decision, str):
        return decision.strip().lower() in {"approve", "approved", "allow", "yes", "y", "true"}
    if isinstance(decision, dict):
        approved = decision.get("approved")
        if isinstance(approved, bool):
            return approved
        if isinstance(approved, str):
            return approved.strip().lower() in {"approve", "approved", "allow", "yes", "y", "true"}
    return False


def _tool_calls_from_last_message(state: AgentState) -> list[dict[str, Any]]:
    messages = list(state.get("messages") or [])
    if not messages:
        return []
    last = messages[-1]
    return list(getattr(last, "tool_calls", None) or [])


def _is_sensitive_call(tool_name: str, args: Any) -> bool:
    if tool_name in SENSITIVE_TOOLS:
        return True
    args_text = json.dumps(args, ensure_ascii=True) if not isinstance(args, str) else args
    return bool(SENSITIVE_PATTERN_RE.search(args_text))


async def security_proxy_node(state: AgentState) -> AgentState:
    """
    Validate proposed tool calls and gate execution.
    - Safe calls pass through.
    - Sensitive calls trigger HITL interrupt.
    """
    tool_calls = _tool_calls_from_last_message(state)
    if not tool_calls:
        return {
            "execution_approved": False,
            "security_decision": "denied",
            "security_reason": "No tool call found for security validation.",
            # Routed here when pending_tool_calls was True; clear so checkpoint state matches reality.
            "pending_tool_calls": False,
        }

    sensitive_calls: list[dict[str, Any]] = []
    safe_calls: list[dict[str, Any]] = []
    for call in tool_calls:
        name = str(call.get("name", "unknown"))
        args = call.get("args", {})
        if _is_sensitive_call(name, args):
            sensitive_calls.append(call)
        else:
            safe_calls.append(call)

    if not sensitive_calls:
        return {
            "execution_approved": True,
            "security_decision": "approved",
            "security_reason": None,
            "pending_tool_names": [str(c.get("name", "unknown")) for c in safe_calls],
        }

    decision = interrupt(
        {
            "type": "security_approval_required",
            "title": "Sensitive tool request blocked pending approval",
            "reason": "One or more tool calls are marked sensitive by policy.",
            "sensitive_tool_calls": sensitive_calls,
            "safe_tool_calls": safe_calls,
            "instruction": "Resume with {\"approved\": true} to allow, or {\"approved\": false} to deny.",
        }
    )
    approved = _normalize_approval(decision)

    if approved:
        approved_tools = [str(c.get("name", "unknown")) for c in tool_calls]
        return {
            "execution_approved": True,
            "security_decision": "approved",
            "security_reason": "Approved by human reviewer.",
            "pending_tool_names": approved_tools,
        }

    denied_message = AIMessage(
        content=(
            "I stopped that action because it requires explicit approval and was not approved. "
            "I can suggest a safer alternative if you want."
        )
    )
    return {
        "messages": [denied_message],
        "execution_approved": False,
        "security_decision": "denied",
        "security_reason": "Sensitive tool request denied by human reviewer.",
        "pending_tool_calls": False,
    }
