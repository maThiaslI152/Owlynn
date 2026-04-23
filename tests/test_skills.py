"""Tests for the skills system."""
import sys
from unittest.mock import MagicMock
sys.modules["mem0"] = MagicMock()

import pytest
from src.tools.skills import (
    load_all_skills,
    find_matching_skill,
    _parse_front_matter,
    list_skills,
    invoke_skill,
)


def test_parse_front_matter():
    text = """---
name: Test Skill
triggers: [hello, world]
description: A test skill
---
This is the prompt body."""
    meta, body = _parse_front_matter(text)
    assert meta["name"] == "Test Skill"
    assert meta["triggers"] == ["hello", "world"]
    assert body == "This is the prompt body."


def test_parse_front_matter_no_meta():
    text = "Just a plain prompt."
    meta, body = _parse_front_matter(text)
    assert meta == {}
    assert body == "Just a plain prompt."


def test_load_all_skills():
    skills = load_all_skills()
    assert len(skills) >= 11  # We created 11 skills
    names = [s["name"] for s in skills]
    assert "Research Assistant" in names
    assert "Visual Comparison" in names
    assert "Brainstorm" in names


def test_find_matching_skill_research():
    skill = find_matching_skill("research the latest AI developments")
    assert skill is not None
    assert "Research" in skill["name"]


def test_find_matching_skill_compare():
    skill = find_matching_skill("Compare AWS vs GCP pricing")
    assert skill is not None
    assert "Comparison" in skill["name"] or "compare" in str(skill.get("triggers", []))


def test_find_matching_skill_no_match():
    skill = find_matching_skill("xyzzy foobar nonsense")
    assert skill is None


def test_list_skills_tool():
    result = list_skills.invoke({})
    assert "Available Skills" in result
    assert "Research Assistant" in result


def test_invoke_skill_found():
    result = invoke_skill.invoke({"skill_name": "Research Assistant", "context": "AI trends"})
    assert "[Skill: Research Assistant]" in result
    assert "web_search" in result or "search" in result.lower()


def test_invoke_skill_not_found():
    result = invoke_skill.invoke({"skill_name": "Nonexistent Skill"})
    assert "not found" in result.lower()
