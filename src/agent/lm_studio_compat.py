"""
LM Studio (Qwen 3.x) Jinja chat templates often require a concrete **user** message.
Requests that are only a system message, or some system+user shapes sent via OpenAI API,
can raise: 'No user query found in messages.'

When ``lm_studio_fold_system`` is true in user profile (default), we merge the system
instructions into the **first** human turn so the API message list starts with ``user``.
"""

from __future__ import annotations

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage

from src.memory.user_profile import get_profile


def lm_studio_fold_system_enabled() -> bool:
    return bool(get_profile().get("lm_studio_fold_system", True))


def fold_system_into_first_user(
    system: SystemMessage,
    thread_messages: list[BaseMessage],
) -> list[BaseMessage]:
    """
    Replace ``[system] + thread`` with a list whose first human message contains
    the system text prepended, preserving the rest of the thread.
    If there is no human message, fall back to ``[system, *thread]``.
    """
    sys_txt = system.content
    if not isinstance(sys_txt, str):
        sys_txt = str(sys_txt)
    sys_txt = sys_txt.strip()

    out: list[BaseMessage] = []
    merged = False
    for m in thread_messages:
        if not merged and getattr(m, "type", None) == "human":
            merged = True
            c = m.content
            if isinstance(c, str):
                new_c = f"{sys_txt}\n\n{c}" if sys_txt else c
            elif isinstance(c, list):
                new_c: list = [{"type": "text", "text": f"{sys_txt}\n\n"}]
                for block in c:
                    new_c.append(block)
            else:
                new_c = f"{sys_txt}\n\n{c}"
            out.append(HumanMessage(content=new_c))
        else:
            out.append(m)

    if not merged:
        return [system, *thread_messages]
    return out


def with_system_for_local_server(
    system: SystemMessage,
    thread_messages: list[BaseMessage],
) -> list[BaseMessage]:
    """Apply folding when enabled; otherwise standard OpenAI-style system + thread."""
    if lm_studio_fold_system_enabled():
        return fold_system_into_first_user(system, thread_messages)
    return [system, *thread_messages]
