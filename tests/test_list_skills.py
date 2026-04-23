"""Unit tests for the enhanced list_skills tool with category filtering (Task 8.1)."""

import sys
from pathlib import Path
from unittest.mock import MagicMock

sys.modules["mem0"] = MagicMock()

import pytest

from src.tools.skills import (
    SkillLoader,
    SkillDefinition,
    list_skills,
    _default_loader,
)


SKILL_GENERAL = """\
---
name: Test General
triggers: [test]
description: A general skill
category: general
---
Do {context}.
"""

SKILL_RESEARCH = """\
---
name: Research Helper
triggers: [research]
description: Helps with research
category: research
---
Research {context}.
"""

SKILL_PRODUCTIVITY = """\
---
name: Morning Briefing
triggers: [briefing, morning]
description: Daily briefing
category: productivity
---
Brief {context}.
"""


def _write_skill(skills_dir: Path, filename: str, content: str) -> None:
    (skills_dir / filename).write_text(content, encoding="utf-8")


@pytest.fixture
def skills_dir(tmp_path: Path) -> Path:
    d = tmp_path / "skills"
    d.mkdir()
    return d


@pytest.fixture
def loader(skills_dir: Path) -> SkillLoader:
    return SkillLoader(skills_dir)


@pytest.fixture(autouse=True)
def _patch_default_loader(loader: SkillLoader, monkeypatch: pytest.MonkeyPatch):
    """Patch the module-level _default_loader so list_skills uses our test loader."""
    monkeypatch.setattr("src.tools.skills._default_loader", loader)


class TestListSkillsNoCategory:
    """list_skills called without category returns all skills grouped by category."""

    def test_returns_all_skills_grouped(self, skills_dir: Path):
        _write_skill(skills_dir, "general.md", SKILL_GENERAL)
        _write_skill(skills_dir, "research.md", SKILL_RESEARCH)
        _write_skill(skills_dir, "prod.md", SKILL_PRODUCTIVITY)
        result = list_skills.invoke({})
        assert "📚 Available Skills:" in result
        assert "📂 general:" in result
        assert "📂 research:" in result
        assert "📂 productivity:" in result

    def test_shows_name_and_description(self, skills_dir: Path):
        _write_skill(skills_dir, "general.md", SKILL_GENERAL)
        result = list_skills.invoke({})
        assert "Test General" in result
        assert "A general skill" in result

    def test_no_skills_returns_message(self):
        result = list_skills.invoke({})
        assert result == "No skills found."


class TestListSkillsWithCategory:
    """list_skills called with a category returns only matching skills."""

    def test_filters_by_category(self, skills_dir: Path):
        _write_skill(skills_dir, "general.md", SKILL_GENERAL)
        _write_skill(skills_dir, "research.md", SKILL_RESEARCH)
        result = list_skills.invoke({"category": "research"})
        assert "Research Helper" in result
        assert "Test General" not in result

    def test_shows_category_header(self, skills_dir: Path):
        _write_skill(skills_dir, "research.md", SKILL_RESEARCH)
        result = list_skills.invoke({"category": "research"})
        assert "📂 research:" in result

    def test_no_skills_in_category_returns_message(self, skills_dir: Path):
        _write_skill(skills_dir, "general.md", SKILL_GENERAL)
        result = list_skills.invoke({"category": "writing"})
        assert result == "No skills found in category 'writing'."

    def test_shows_name_and_description(self, skills_dir: Path):
        _write_skill(skills_dir, "research.md", SKILL_RESEARCH)
        result = list_skills.invoke({"category": "research"})
        assert "Research Helper" in result
        assert "Helps with research" in result
