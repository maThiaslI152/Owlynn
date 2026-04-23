"""Tests for SkillParam and SkillDefinition dataclasses."""
import sys
from unittest.mock import MagicMock
sys.modules["mem0"] = MagicMock()

import pytest
from src.tools.skills import SkillParam, SkillDefinition, ALLOWED_CATEGORIES


def _make_skill(**overrides) -> SkillDefinition:
    """Helper to create a valid SkillDefinition with sensible defaults."""
    defaults = {
        "file": "test.md",
        "name": "Test Skill",
        "triggers": ["test"],
        "description": "A test skill",
        "prompt": "Do the thing with {context}",
    }
    defaults.update(overrides)
    return SkillDefinition(**defaults)


class TestSkillParam:
    def test_basic_creation(self):
        p = SkillParam(name="depth", description="How deep", required=True, default=None)
        assert p.name == "depth"
        assert p.description == "How deep"
        assert p.required is True
        assert p.default is None

    def test_optional_param_with_default(self):
        p = SkillParam(name="format", description="Output format", required=False, default="json")
        assert p.required is False
        assert p.default == "json"

    def test_defaults(self):
        p = SkillParam(name="x", description="y")
        assert p.required is True
        assert p.default is None


class TestSkillDefinition:
    def test_valid_creation(self):
        s = _make_skill()
        assert s.name == "Test Skill"
        assert s.category == "general"
        assert s.params == []
        assert s.chain_compatible is True
        assert s.version == "1.0"
        assert s.tools_used == []

    def test_all_fields(self):
        params = [SkillParam("a", "desc a"), SkillParam("b", "desc b")]
        s = _make_skill(
            category="research",
            params=params,
            chain_compatible=False,
            version="2.0",
            tools_used=["web_search"],
        )
        assert s.category == "research"
        assert len(s.params) == 2
        assert s.chain_compatible is False
        assert s.version == "2.0"
        assert s.tools_used == ["web_search"]

    def test_empty_name_raises(self):
        with pytest.raises(ValueError, match="name must be non-empty"):
            _make_skill(name="")

    def test_whitespace_name_raises(self):
        with pytest.raises(ValueError, match="name must be non-empty"):
            _make_skill(name="   ")

    def test_empty_triggers_raises(self):
        with pytest.raises(ValueError, match="triggers must contain at least one entry"):
            _make_skill(triggers=[])

    def test_empty_prompt_raises(self):
        with pytest.raises(ValueError, match="prompt must be non-empty"):
            _make_skill(prompt="")

    def test_whitespace_prompt_raises(self):
        with pytest.raises(ValueError, match="prompt must be non-empty"):
            _make_skill(prompt="   ")

    def test_invalid_category_raises(self):
        with pytest.raises(ValueError, match="Invalid category"):
            _make_skill(category="invalid")

    def test_all_valid_categories(self):
        for cat in ALLOWED_CATEGORIES:
            s = _make_skill(category=cat)
            assert s.category == cat

    def test_duplicate_param_names_raises(self):
        params = [
            SkillParam("depth", "first"),
            SkillParam("depth", "second"),
        ]
        with pytest.raises(ValueError, match="param names must be unique"):
            _make_skill(params=params)

    def test_unique_param_names_ok(self):
        params = [
            SkillParam("depth", "first"),
            SkillParam("format", "second"),
        ]
        s = _make_skill(params=params)
        assert len(s.params) == 2
