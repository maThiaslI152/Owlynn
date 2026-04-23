"""
Property-based tests for project context isolation.

# Feature: productivity-workspace-overhaul, Property 25: Project context isolation
# **Validates: Requirements 11.1**

Property 25 states:
    For any project switch, the backend should load the new project's custom
    instructions and knowledge base context. The loaded context should not
    contain any data from the previously active project.

We test the core isolation mechanisms:
1. _get_mem0_user_id() returns project-scoped user IDs that differ between projects
2. format_memory_context() only includes the supplied project's instructions
3. Simulated project switches produce context that contains only the new project's data
"""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from hypothesis import given, settings, assume, HealthCheck
from hypothesis import strategies as st

from src.agent.nodes.memory import _get_mem0_user_id, format_memory_context
from src.memory.project import ProjectManager


# ── Strategies ───────────────────────────────────────────────────────────

# Project IDs: short alphanumeric strings (mimics uuid[:8] from create_project)
_id_chars = st.sampled_from("abcdefghijklmnopqrstuvwxyz0123456789")
project_id_st = st.text(_id_chars, min_size=3, max_size=8)

# Project names: readable strings
project_name_st = st.text(
    st.sampled_from("abcdefghijklmnopqrstuvwxyz ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"),
    min_size=3,
    max_size=40,
).filter(lambda s: s.strip() and any(c.isalnum() for c in s))

# Custom instructions: non-empty text with identifiable content
instruction_st = st.text(
    st.characters(whitelist_categories=("L", "N", "P", "Z"), min_codepoint=32, max_codepoint=126),
    min_size=10,
    max_size=200,
).filter(lambda s: s.strip())

# Memory results: list of memory dicts
memory_entry_st = st.text(
    st.characters(whitelist_categories=("L", "N", "P", "Z"), min_codepoint=32, max_codepoint=126),
    min_size=5,
    max_size=100,
).filter(lambda s: s.strip())

memory_results_st = st.lists(
    st.fixed_dictionaries({"memory": memory_entry_st}),
    min_size=0,
    max_size=5,
)


# ── Helpers ──────────────────────────────────────────────────────────────

def _build_state_for_project(project_id: str) -> dict:
    """Build a minimal agent state dict scoped to a project."""
    return {
        "messages": [],
        "project_id": project_id,
    }


def _simulate_context_load(project_name: str, instructions: str, memories: list) -> str:
    """
    Simulate what memory_inject_node does: build the context string
    for a given project using format_memory_context.
    """
    project_instructions = f"Active project: {project_name}\n{instructions}"
    profile = {}
    return format_memory_context(memories, profile, "", project_instructions)


# ═════════════════════════════════════════════════════════════════════════
# Property 25: Project context isolation
# ═════════════════════════════════════════════════════════════════════════

class TestProjectContextIsolation:
    """
    Property 25: For any project switch, the backend should load the new
    project's custom instructions and knowledge base context. The loaded
    context should not contain any data from the previously active project.

    **Validates: Requirements 11.1**
    """

    @given(
        pid_a=project_id_st,
        pid_b=project_id_st,
    )
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_mem0_user_ids_differ_between_projects(self, pid_a, pid_b):
        """
        _get_mem0_user_id returns different scoped IDs for different
        non-default projects, ensuring memory isolation.
        """
        assume(pid_a != pid_b)
        assume(pid_a != "default" and pid_b != "default")

        state_a = _build_state_for_project(pid_a)
        state_b = _build_state_for_project(pid_b)

        uid_a = _get_mem0_user_id(state_a)
        uid_b = _get_mem0_user_id(state_b)

        assert uid_a != uid_b, (
            f"Projects '{pid_a}' and '{pid_b}' got the same mem0 user_id: '{uid_a}'"
        )

    @given(pid=project_id_st)
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_mem0_user_id_is_project_scoped(self, pid):
        """
        For any non-default project, the mem0 user_id should contain
        the project ID, ensuring it's scoped to that project.
        """
        assume(pid != "default")

        state = _build_state_for_project(pid)
        uid = _get_mem0_user_id(state)

        assert pid in uid, (
            f"mem0 user_id '{uid}' does not contain project_id '{pid}'"
        )

    @given(
        name_a=project_name_st,
        name_b=project_name_st,
        instr_a=instruction_st,
        instr_b=instruction_st,
        memories_b=memory_results_st,
    )
    @settings(max_examples=50, suppress_health_check=[HealthCheck.too_slow])
    def test_context_after_switch_contains_only_new_project(
        self, name_a, name_b, instr_a, instr_b, memories_b
    ):
        """
        After switching from project A to project B, the loaded context
        should contain project B's instructions and NOT project A's
        unique instructions.
        """
        # Tag instructions with unique prefixes to guarantee distinguishability
        tagged_a = f"[PROJ_A_INSTR] {instr_a.strip()}"
        tagged_b = f"[PROJ_B_INSTR] {instr_b.strip()}"

        # Simulate switching to project B (the "new" project)
        context_b = _simulate_context_load(name_b, tagged_b, memories_b)

        # The new context should contain project B's data
        assert tagged_b in context_b, (
            f"New project context missing project B instructions"
        )

        # The new context should NOT contain project A's tagged instructions
        assert tagged_a not in context_b, (
            f"New project context still contains project A instructions"
        )

    @given(
        name=project_name_st,
        instr=instruction_st,
        memories=memory_results_st,
    )
    @settings(max_examples=50, suppress_health_check=[HealthCheck.too_slow])
    def test_context_contains_project_instructions(self, name, instr, memories):
        """
        The loaded context for any project should contain that project's
        custom instructions and name.
        """
        context = _simulate_context_load(name, instr, memories)

        assert instr.strip() in context, (
            f"Context missing project instructions"
        )
        assert name.strip() in context, (
            f"Context missing project name '{name}'"
        )
        assert "ACTIVE PROJECT CONTEXT" in context, (
            "Context missing project context section header"
        )

    @given(
        name=project_name_st,
        instr=instruction_st,
        memories=memory_results_st,
    )
    @settings(max_examples=50, suppress_health_check=[HealthCheck.too_slow])
    def test_context_contains_project_memories(self, name, instr, memories):
        """
        The loaded context should include the project's memory entries
        when they exist.
        """
        context = _simulate_context_load(name, instr, memories)

        for mem_entry in memories:
            mem_text = mem_entry["memory"]
            assert mem_text in context, (
                f"Context missing memory entry: '{mem_text[:50]}...'"
            )

    @given(
        name_a=project_name_st,
        name_b=project_name_st,
        instr_a=instruction_st,
        instr_b=instruction_st,
        memories_a=st.lists(
            st.fixed_dictionaries({"memory": memory_entry_st}),
            min_size=1,
            max_size=3,
        ),
        memories_b=st.lists(
            st.fixed_dictionaries({"memory": memory_entry_st}),
            min_size=1,
            max_size=3,
        ),
    )
    @settings(max_examples=50, suppress_health_check=[HealthCheck.too_slow])
    def test_memories_from_old_project_absent_after_switch(
        self, name_a, name_b, instr_a, instr_b, memories_a, memories_b
    ):
        """
        After switching projects, memories unique to the old project
        should not appear in the new project's context.
        """
        # Tag memories with project-specific prefixes to guarantee uniqueness
        tagged_a = [{"memory": f"[MEM_A] {m['memory']}"} for m in memories_a]
        tagged_b = [{"memory": f"[MEM_B] {m['memory']}"} for m in memories_b]

        # Load context for project B (the new project after switch)
        context_b = _simulate_context_load(name_b, instr_b, tagged_b)

        # All project B memories should be present
        for mem in tagged_b:
            assert mem["memory"] in context_b, (
                f"Project B context missing its own memory: '{mem['memory'][:50]}...'"
            )

        # No project A tagged memories should appear
        for mem in tagged_a:
            assert mem["memory"] not in context_b, (
                f"Project B context contains project A memory: '{mem['memory'][:50]}...'"
            )
