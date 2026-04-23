"""
Property-Based Tests for ProjectManager CRUD Operations
=========================================================

Uses Hypothesis to generate random project names, chat names, and chat IDs,
then verifies invariants that must hold for ALL inputs — not just hand-picked
examples. This catches edge cases that unit tests miss (unicode, empty strings,
very long names, special characters).

Properties tested:
1. **Create-Get Roundtrip**: create → get returns identical data
2. **Rename Isolation**: renaming changes only the name field
3. **Delete Completeness**: deleted projects are fully gone
4. **Default Protection**: the "default" project can never be deleted
5. **Chat Dedup**: adding the same chat ID twice results in one entry
6. **Chat Rename Isolation**: renaming a chat preserves id and timestamp
7. **Chat Delete Count**: deleting a chat decreases count by exactly 1
8. **Nonexistent Operations Safe**: operations on missing IDs never raise

Each test creates and cleans up its own ProjectManager instance to avoid
cross-test interference. ``max_examples=100`` balances coverage vs speed.

Run: ``pytest tests/test_crud_properties.py -v --hypothesis-show-statistics``
"""

import os
import sys
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from hypothesis import given, settings
from hypothesis.strategies import text, uuids
from hypothesis import strategies as st
from src.memory.project import ProjectManager

# --- Strategies (Req 8.2, 8.3) ---
# Hypothesis strategies for generating random but valid test inputs.
# project_names: arbitrary unicode strings (1-200 chars) to stress-test name handling.
# chat_names: same range for chat names.
# chat_ids: UUID strings to match the backend's expected chat ID format.
project_names = text(min_size=1, max_size=200)
chat_names = text(min_size=1, max_size=200)
chat_ids = uuids().map(str)


# --- Property 1: Create-Get Roundtrip ---
# Validates: Requirements 1.1, 1.2, 1.3, 1.5, 1.6, 1.7, 8.4
@settings(max_examples=100)
@given(name=project_names)
def test_create_get_roundtrip(name):
    pm = ProjectManager()
    try:
        project = pm.create_project(name)
        assert project["name"] == name
        assert len(project["id"]) == 8
        assert project["chats"] == []
        assert project["files"] == []
        assert project["category"] == "general"

        fetched = pm.get_project(project["id"])
        assert fetched is not None
        assert fetched["name"] == name
        assert fetched["id"] == project["id"]
    finally:
        pm.delete_project(project["id"])


# --- Property 2: Rename Isolation ---
# Validates: Requirements 2.1, 2.2, 2.4, 8.5
@settings(max_examples=100)
@given(name=project_names, new_name=project_names)
def test_rename_isolation(name, new_name):
    pm = ProjectManager()
    try:
        project = pm.create_project(name)
        pid = project["id"]
        original_id = project["id"]
        original_instructions = project["instructions"]
        original_chats = list(project["chats"])
        original_files = list(project["files"])
        original_category = project["category"]

        updated = pm.update_project(pid, name=new_name)
        assert updated is not None
        assert updated["name"] == new_name
        assert updated["id"] == original_id
        assert updated["instructions"] == original_instructions
        assert updated["chats"] == original_chats
        assert updated["files"] == original_files
        assert updated["category"] == original_category
    finally:
        pm.delete_project(project["id"])


# --- Property 3: Delete Completeness ---
# Validates: Requirements 3.1, 3.4, 8.6
@settings(max_examples=100)
@given(name=project_names)
def test_delete_completeness(name):
    pm = ProjectManager()
    project = pm.create_project(name)
    pid = project["id"]
    result = pm.delete_project(pid)
    assert result is True
    assert pm.get_project(pid) is None


# --- Property 4: Default Protection ---
# Validates: Requirements 3.2, 10.3
@settings(max_examples=100)
@given(name=project_names)
def test_default_protection(name):
    pm = ProjectManager()
    try:
        # Create a project just to exercise the PM with random input
        project = pm.create_project(name)

        # The actual property: default cannot be deleted
        default_before = pm.get_project("default")
        assert default_before is not None

        result = pm.delete_project("default")
        assert result is False

        default_after = pm.get_project("default")
        assert default_after is not None
        assert default_after["id"] == "default"
        assert default_after["name"] == default_before["name"]
    finally:
        pm.delete_project(project["id"])


# --- Property 5: Chat Dedup ---
# Validates: Requirements 4.1, 4.2, 4.4, 8.7
@settings(max_examples=100)
@given(name=project_names, chat_name=chat_names, chat_id=chat_ids)
def test_chat_dedup(name, chat_name, chat_id):
    pm = ProjectManager()
    try:
        project = pm.create_project(name)
        pid = project["id"]
        chat_info = {"id": chat_id, "name": chat_name, "created_at": time.time()}

        pm.add_chat_to_project(pid, chat_info)
        pm.add_chat_to_project(pid, {"id": chat_id, "name": "duplicate", "created_at": 0})

        fetched = pm.get_project(pid)
        matching = [c for c in fetched["chats"] if c["id"] == chat_id]
        assert len(matching) == 1
    finally:
        pm.delete_project(project["id"])


# --- Property 6: Chat Rename Isolation ---
# Validates: Requirements 5.1, 5.2, 5.4, 8.8
@settings(max_examples=100)
@given(name=project_names, chat_name=chat_names, new_chat_name=chat_names, chat_id=chat_ids)
def test_chat_rename_isolation(name, chat_name, new_chat_name, chat_id):
    pm = ProjectManager()
    try:
        project = pm.create_project(name)
        pid = project["id"]
        created_at = time.time()
        chat_info = {"id": chat_id, "name": chat_name, "created_at": created_at}
        pm.add_chat_to_project(pid, chat_info)

        pm.update_chat_in_project(pid, chat_id, name=new_chat_name)

        fetched = pm.get_project(pid)
        chat = next(c for c in fetched["chats"] if c["id"] == chat_id)
        assert chat["name"] == new_chat_name
        assert chat["id"] == chat_id
        assert chat["created_at"] == created_at
    finally:
        pm.delete_project(project["id"])


# --- Property 7: Chat Delete Count ---
# Validates: Requirements 6.1, 6.2, 8.9
@settings(max_examples=100)
@given(name=project_names, chat_name=chat_names, chat_id=chat_ids)
def test_chat_delete_count(name, chat_name, chat_id):
    pm = ProjectManager()
    try:
        project = pm.create_project(name)
        pid = project["id"]
        chat_info = {"id": chat_id, "name": chat_name, "created_at": time.time()}
        pm.add_chat_to_project(pid, chat_info)

        proj_before = pm.get_project(pid)
        n = len(proj_before["chats"])

        pm.delete_chat_from_project(pid, chat_id)

        proj_after = pm.get_project(pid)
        assert len(proj_after["chats"]) == n - 1
        assert not any(c["id"] == chat_id for c in proj_after["chats"])
    finally:
        pm.delete_project(project["id"])


# --- Property 8: Nonexistent Operations Safe ---
# Validates: Requirements 10.1, 10.2
@settings(max_examples=100)
@given(name=project_names, chat_name=chat_names, chat_id=chat_ids)
def test_nonexistent_operations_safe(name, chat_name, chat_id):
    fake_pid = "zz_fake_"
    fake_cid = "zz-fake-chat-id"

    pm = ProjectManager()
    try:
        # Operations on non-existent project ID should not raise
        pm.update_project(fake_pid, name="x")
        pm.delete_project(fake_pid)
        pm.add_chat_to_project(fake_pid, {"id": chat_id, "name": chat_name, "created_at": 0})
        pm.update_chat_in_project(fake_pid, chat_id, name="x")
        pm.delete_chat_from_project(fake_pid, chat_id)

        # Operations on non-existent chat ID within a valid project
        project = pm.create_project(name)
        pid = project["id"]
        pm.update_chat_in_project(pid, fake_cid, name="x")
        pm.delete_chat_from_project(pid, fake_cid)
    finally:
        if 'pid' in locals():
            pm.delete_project(pid)


# --- Property 9: Repeated interleaved CRUD invariants ---
# Validates project-state consistency under long operation sequences.
_op_add = st.tuples(st.just("add"), chat_ids, chat_names)
_op_rename = st.tuples(st.just("rename"), chat_ids, chat_names)
_op_delete = st.tuples(st.just("delete"), chat_ids, st.just(""))
op_sequences = st.lists(st.one_of(_op_add, _op_rename, _op_delete), min_size=20, max_size=50)


@settings(max_examples=40)
@given(name=project_names, ops=op_sequences)
def test_interleaved_operation_sequence_preserves_invariants(name, ops):
    pm = ProjectManager()
    project = pm.create_project(name)
    pid = project["id"]
    expected_ids = set()
    try:
        for op, chat_id, chat_name in ops:
            if op == "add":
                pm.add_chat_to_project(pid, {"id": chat_id, "name": chat_name, "created_at": time.time()})
                expected_ids.add(chat_id)
            elif op == "rename":
                pm.update_chat_in_project(pid, chat_id, name=chat_name)
            elif op == "delete":
                pm.delete_chat_from_project(pid, chat_id)
                expected_ids.discard(chat_id)

            current = pm.get_project(pid)
            chats = current["chats"]
            ids = [c.get("id") for c in chats]
            # Invariant 1: no duplicate chat IDs
            assert len(ids) == len(set(ids))
            # Invariant 2: persisted IDs match expected add/delete model
            assert set(ids) == expected_ids
    finally:
        pm.delete_project(pid)
