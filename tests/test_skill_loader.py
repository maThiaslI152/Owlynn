"""Unit tests for the SkillLoader class."""

import time
from pathlib import Path

import pytest

from src.tools.skills import SkillLoader, SkillDefinition


VALID_SKILL_MD = """\
---
name: Test Skill
triggers: [test, demo]
description: A test skill
category: general
---
Do something with {context}.
"""

VALID_SKILL_V2_MD = """\
---
name: Research Helper
triggers: [research, investigate]
description: Helps with research
category: research
params:
  - name: depth
    description: How deep
    required: false
    default: standard
tools_used: [web_search]
chain_compatible: true
version: "2.0"
---
Research {context} at depth {depth}.
"""

INVALID_SKILL_MD = """\
---
name:
triggers: []
description: broken
---
No triggers here.
"""


@pytest.fixture
def skills_dir(tmp_path: Path) -> Path:
    d = tmp_path / "skills"
    d.mkdir()
    return d


@pytest.fixture
def loader(skills_dir: Path) -> SkillLoader:
    return SkillLoader(skills_dir)


def _write_skill(skills_dir: Path, filename: str, content: str) -> None:
    (skills_dir / filename).write_text(content, encoding="utf-8")


class TestLoadAll:
    def test_returns_skill_definitions(self, loader: SkillLoader, skills_dir: Path):
        _write_skill(skills_dir, "test.md", VALID_SKILL_MD)
        result = loader.load_all()
        assert len(result) == 1
        assert isinstance(result[0], SkillDefinition)
        assert result[0].name == "Test Skill"

    def test_loads_multiple_files(self, loader: SkillLoader, skills_dir: Path):
        _write_skill(skills_dir, "a.md", VALID_SKILL_MD)
        _write_skill(skills_dir, "b.md", VALID_SKILL_V2_MD)
        result = loader.load_all()
        assert len(result) == 2

    def test_skips_invalid_files(self, loader: SkillLoader, skills_dir: Path):
        _write_skill(skills_dir, "good.md", VALID_SKILL_MD)
        _write_skill(skills_dir, "bad.md", INVALID_SKILL_MD)
        result = loader.load_all()
        assert len(result) == 1
        assert result[0].name == "Test Skill"

    def test_returns_empty_for_no_files(self, loader: SkillLoader):
        assert loader.load_all() == []

    def test_cache_returns_same_results(self, loader: SkillLoader, skills_dir: Path):
        _write_skill(skills_dir, "test.md", VALID_SKILL_MD)
        first = loader.load_all()
        second = loader.load_all()
        assert first == second

    def test_cache_within_ttl(self, loader: SkillLoader, skills_dir: Path):
        _write_skill(skills_dir, "test.md", VALID_SKILL_MD)
        loader.load_all()
        # Add a new file — should NOT appear because cache is still valid
        _write_skill(skills_dir, "new.md", VALID_SKILL_V2_MD)
        result = loader.load_all()
        assert len(result) == 1


class TestLoadOne:
    def test_loads_single_file(self, loader: SkillLoader, skills_dir: Path):
        _write_skill(skills_dir, "test.md", VALID_SKILL_MD)
        skill = loader.load_one("test.md")
        assert skill is not None
        assert skill.name == "Test Skill"

    def test_returns_none_for_missing(self, loader: SkillLoader):
        assert loader.load_one("nonexistent.md") is None

    def test_returns_none_for_invalid(self, loader: SkillLoader, skills_dir: Path):
        _write_skill(skills_dir, "bad.md", INVALID_SKILL_MD)
        assert loader.load_one("bad.md") is None

    def test_updates_cache(self, loader: SkillLoader, skills_dir: Path):
        _write_skill(skills_dir, "test.md", VALID_SKILL_MD)
        loader.load_one("test.md")
        assert "test.md" in loader._cache


class TestInvalidateCache:
    def test_clears_cache(self, loader: SkillLoader, skills_dir: Path):
        _write_skill(skills_dir, "test.md", VALID_SKILL_MD)
        loader.load_all()
        assert len(loader._cache) == 1
        loader.invalidate_cache()
        assert len(loader._cache) == 0
        assert loader._last_scan == 0.0

    def test_next_load_all_rereads(self, loader: SkillLoader, skills_dir: Path):
        _write_skill(skills_dir, "test.md", VALID_SKILL_MD)
        loader.load_all()
        _write_skill(skills_dir, "new.md", VALID_SKILL_V2_MD)
        loader.invalidate_cache()
        result = loader.load_all()
        assert len(result) == 2


class TestGetByName:
    def test_finds_by_exact_name(self, loader: SkillLoader, skills_dir: Path):
        _write_skill(skills_dir, "test.md", VALID_SKILL_MD)
        loader.load_all()
        skill = loader.get_by_name("Test Skill")
        assert skill is not None
        assert skill.name == "Test Skill"

    def test_case_insensitive(self, loader: SkillLoader, skills_dir: Path):
        _write_skill(skills_dir, "test.md", VALID_SKILL_MD)
        loader.load_all()
        assert loader.get_by_name("test skill") is not None
        assert loader.get_by_name("TEST SKILL") is not None

    def test_returns_none_for_unknown(self, loader: SkillLoader, skills_dir: Path):
        _write_skill(skills_dir, "test.md", VALID_SKILL_MD)
        loader.load_all()
        assert loader.get_by_name("nonexistent") is None

    def test_auto_loads_if_cache_empty(self, loader: SkillLoader, skills_dir: Path):
        _write_skill(skills_dir, "test.md", VALID_SKILL_MD)
        # Don't call load_all first — get_by_name should trigger it
        skill = loader.get_by_name("Test Skill")
        assert skill is not None


class TestGetByCategory:
    def test_filters_by_category(self, loader: SkillLoader, skills_dir: Path):
        _write_skill(skills_dir, "a.md", VALID_SKILL_MD)       # general
        _write_skill(skills_dir, "b.md", VALID_SKILL_V2_MD)    # research
        loader.load_all()
        general = loader.get_by_category("general")
        research = loader.get_by_category("research")
        assert len(general) == 1
        assert len(research) == 1
        assert general[0].category == "general"
        assert research[0].category == "research"

    def test_returns_empty_for_no_match(self, loader: SkillLoader, skills_dir: Path):
        _write_skill(skills_dir, "test.md", VALID_SKILL_MD)
        loader.load_all()
        assert loader.get_by_category("writing") == []

    def test_auto_loads_if_cache_empty(self, loader: SkillLoader, skills_dir: Path):
        _write_skill(skills_dir, "test.md", VALID_SKILL_MD)
        result = loader.get_by_category("general")
        assert len(result) == 1
