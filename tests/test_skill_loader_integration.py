"""Tests for task 2.2: SkillLoader integration into tool functions and deprecated wrappers."""

import sys
import warnings
from pathlib import Path
from unittest.mock import MagicMock

sys.modules["mem0"] = MagicMock()

import pytest

from src.tools.skills import (
    SkillLoader,
    SkillDefinition,
    _default_loader,
    load_all_skills,
    find_matching_skill,
    list_skills,
    invoke_skill,
    SKILLS_DIR,
)


class TestDefaultLoader:
    def test_default_loader_exists(self):
        assert _default_loader is not None
        assert isinstance(_default_loader, SkillLoader)

    def test_default_loader_points_to_skills_dir(self):
        assert _default_loader._skills_dir == SKILLS_DIR


class TestDeprecatedLoadAllSkills:
    def test_emits_deprecation_warning(self):
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            load_all_skills()
            dep_warnings = [x for x in w if issubclass(x.category, DeprecationWarning)]
            assert len(dep_warnings) == 1
            assert "deprecated" in str(dep_warnings[0].message).lower()

    def test_returns_list_of_dicts(self):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            result = load_all_skills()
        assert isinstance(result, list)
        if result:
            assert isinstance(result[0], dict)
            assert "name" in result[0]
            assert "triggers" in result[0]
            assert "description" in result[0]
            assert "prompt" in result[0]
            assert "file" in result[0]

    def test_returns_same_skills_as_loader(self):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            dict_skills = load_all_skills()
        loader_skills = _default_loader.load_all()
        assert len(dict_skills) == len(loader_skills)
        dict_names = sorted(s["name"] for s in dict_skills)
        loader_names = sorted(s.name for s in loader_skills)
        assert dict_names == loader_names


class TestDeprecatedFindMatchingSkill:
    def test_emits_deprecation_warning(self):
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            find_matching_skill("research something")
            dep_warnings = [x for x in w if issubclass(x.category, DeprecationWarning)]
            assert len(dep_warnings) >= 1
            assert "deprecated" in str(dep_warnings[0].message).lower()

    def test_finds_skill_by_trigger(self):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            result = find_matching_skill("research the latest AI developments")
        assert result is not None
        assert isinstance(result, dict)
        assert "Research" in result["name"]

    def test_returns_none_for_no_match(self):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            result = find_matching_skill("xyzzy foobar nonsense")
        assert result is None

    def test_returns_dict_with_expected_keys(self):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            result = find_matching_skill("research something")
        if result is not None:
            assert "file" in result
            assert "name" in result
            assert "triggers" in result
            assert "description" in result
            assert "prompt" in result


class TestListSkillsUsesLoader:
    def test_returns_available_skills(self):
        result = list_skills.invoke({})
        assert "Available Skills" in result

    def test_contains_skill_names(self):
        result = list_skills.invoke({})
        assert "Research Assistant" in result

    def test_groups_by_category(self):
        result = list_skills.invoke({})
        assert "📂" in result


class TestInvokeSkillUsesLoader:
    def test_invokes_by_name(self):
        result = invoke_skill.invoke({"skill_name": "Research Assistant", "context": "AI trends"})
        assert "[Skill: Research Assistant]" in result

    def test_case_insensitive_lookup(self):
        result = invoke_skill.invoke({"skill_name": "research assistant", "context": "test"})
        assert "[Skill: Research Assistant]" in result

    def test_not_found_lists_available(self):
        result = invoke_skill.invoke({"skill_name": "Nonexistent Skill"})
        assert "not found" in result.lower()
        assert "Available:" in result

    def test_context_injection(self):
        result = invoke_skill.invoke({"skill_name": "Research Assistant", "context": "quantum computing"})
        assert "quantum computing" in result
