"""
Property-based tests for separate chat histories per project.

# Feature: productivity-workspace-overhaul, Property 27: Separate chat histories per project
# **Validates: Requirements 11.5**

Property 27 states:
    For any two projects, adding a chat to one project should not affect
    the other project's chat list. Each project's chats array is independent.

We test the core isolation mechanisms:
1. Adding a chat to project A does not change project B's chat list
2. Multiple chats added to one project leave the other project's chats untouched
3. Deleting a chat from one project does not affect the other project's chats
"""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from hypothesis import given, settings, assume, HealthCheck
from hypothesis import strategies as st

from src.memory.project import ProjectManager


# ── Strategies ───────────────────────────────────────────────────────────

# Chat IDs: short unique strings mimicking UUIDs
_id_chars = st.sampled_from("abcdefghijklmnopqrstuvwxyz0123456789")
chat_id_st = st.text(_id_chars, min_size=4, max_size=12).filter(lambda s: len(s) >= 4)

# Chat names: readable strings
chat_name_st = st.text(
    st.sampled_from("abcdefghijklmnopqrstuvwxyz ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"),
    min_size=3,
    max_size=40,
).filter(lambda s: s.strip())

# Chat info: a dict with id, name, created_at
chat_info_st = st.builds(
    lambda cid, name, ts: {"id": cid, "name": name, "created_at": ts},
    cid=chat_id_st,
    name=chat_name_st,
    ts=st.integers(min_value=1000000000, max_value=2000000000),
)

# Lists of chat infos with unique IDs
chat_list_st = st.lists(
    chat_info_st,
    min_size=1,
    max_size=5,
    unique_by=lambda c: c["id"],
)


# ── Helpers ──────────────────────────────────────────────────────────────

def _create_fresh_manager_with_two_projects():
    """Create a ProjectManager and two fresh test projects, returning (pm, proj_a, proj_b)."""
    pm = ProjectManager()
    proj_a = pm.create_project("Project A")
    proj_b = pm.create_project("Project B")
    return pm, proj_a, proj_b


def _cleanup(pm, *projects):
    """Delete test projects to avoid polluting state."""
    for proj in projects:
        try:
            pm.delete_project(proj["id"])
        except Exception:
            pass


# ═════════════════════════════════════════════════════════════════════════
# Property 27: Separate chat histories per project
# ═════════════════════════════════════════════════════════════════════════

class TestSeparateChatHistories:
    """
    Property 27: For any two projects, adding a chat to one project should
    not affect the other project's chat list. Each project's chats array
    is independent.

    **Validates: Requirements 11.5**
    """

    @given(chat=chat_info_st)
    @settings(max_examples=50, suppress_health_check=[HealthCheck.too_slow])
    def test_adding_chat_to_one_project_does_not_affect_other(self, chat):
        """
        For any chat info, adding it to project A should leave
        project B's chat list completely unchanged.
        """
        pm, proj_a, proj_b = _create_fresh_manager_with_two_projects()
        try:
            # Snapshot project B's chats before
            chats_b_before = list(pm.get_project(proj_b["id"])["chats"])

            # Add chat to project A
            pm.add_chat_to_project(proj_a["id"], chat)

            # Project B's chats should be identical
            chats_b_after = pm.get_project(proj_b["id"])["chats"]
            assert chats_b_after == chats_b_before, (
                f"Project B chats changed after adding chat to Project A. "
                f"Before: {chats_b_before}, After: {chats_b_after}"
            )

            # Project A should have the new chat
            chats_a = pm.get_project(proj_a["id"])["chats"]
            assert any(c["id"] == chat["id"] for c in chats_a), (
                f"Chat '{chat['id']}' not found in Project A after adding"
            )
        finally:
            _cleanup(pm, proj_a, proj_b)

    @given(chats=chat_list_st)
    @settings(max_examples=50, suppress_health_check=[HealthCheck.too_slow])
    def test_multiple_chats_added_to_one_project_leave_other_empty(self, chats):
        """
        Adding multiple chats to project A should keep project B's
        chat list at zero length (both start empty).
        """
        pm, proj_a, proj_b = _create_fresh_manager_with_two_projects()
        try:
            for chat in chats:
                pm.add_chat_to_project(proj_a["id"], chat)

            chats_b = pm.get_project(proj_b["id"])["chats"]
            assert len(chats_b) == 0, (
                f"Project B has {len(chats_b)} chats after adding {len(chats)} to Project A"
            )

            chats_a = pm.get_project(proj_a["id"])["chats"]
            assert len(chats_a) == len(chats), (
                f"Project A should have {len(chats)} chats but has {len(chats_a)}"
            )
        finally:
            _cleanup(pm, proj_a, proj_b)

    @given(
        chat_a=chat_info_st,
        chat_b=chat_info_st,
    )
    @settings(max_examples=50, suppress_health_check=[HealthCheck.too_slow])
    def test_each_project_gets_only_its_own_chats(self, chat_a, chat_b):
        """
        Adding different chats to different projects should result in
        each project containing only its own chat.
        """
        assume(chat_a["id"] != chat_b["id"])

        pm, proj_a, proj_b = _create_fresh_manager_with_two_projects()
        try:
            pm.add_chat_to_project(proj_a["id"], chat_a)
            pm.add_chat_to_project(proj_b["id"], chat_b)

            chats_a = pm.get_project(proj_a["id"])["chats"]
            chats_b = pm.get_project(proj_b["id"])["chats"]

            # Project A has only chat_a
            a_ids = {c["id"] for c in chats_a}
            assert chat_a["id"] in a_ids, "Project A missing its own chat"
            assert chat_b["id"] not in a_ids, "Project A contains Project B's chat"

            # Project B has only chat_b
            b_ids = {c["id"] for c in chats_b}
            assert chat_b["id"] in b_ids, "Project B missing its own chat"
            assert chat_a["id"] not in b_ids, "Project B contains Project A's chat"
        finally:
            _cleanup(pm, proj_a, proj_b)

    @given(
        chat_a=chat_info_st,
        chat_b=chat_info_st,
    )
    @settings(max_examples=50, suppress_health_check=[HealthCheck.too_slow])
    def test_deleting_chat_from_one_project_does_not_affect_other(self, chat_a, chat_b):
        """
        Deleting a chat from project A should not change project B's chats.
        """
        assume(chat_a["id"] != chat_b["id"])

        pm, proj_a, proj_b = _create_fresh_manager_with_two_projects()
        try:
            pm.add_chat_to_project(proj_a["id"], chat_a)
            pm.add_chat_to_project(proj_b["id"], chat_b)

            # Delete chat from project A
            pm.delete_chat_from_project(proj_a["id"], chat_a["id"])

            # Project A should have no chats
            chats_a = pm.get_project(proj_a["id"])["chats"]
            assert len(chats_a) == 0, (
                f"Project A still has {len(chats_a)} chats after deletion"
            )

            # Project B should still have its chat
            chats_b = pm.get_project(proj_b["id"])["chats"]
            assert len(chats_b) == 1, (
                f"Project B should have 1 chat but has {len(chats_b)}"
            )
            assert chats_b[0]["id"] == chat_b["id"], (
                f"Project B's chat ID changed after deleting from Project A"
            )
        finally:
            _cleanup(pm, proj_a, proj_b)
