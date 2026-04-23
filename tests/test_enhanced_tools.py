"""Unit tests for enhanced tool functions: list_skills, invoke_skill, run_skill_chain (Task 8.4).

Validates Requirements: 6.1–6.4, 7.1–7.5, 8.1–8.4
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock

sys.modules["mem0"] = MagicMock()

import pytest

from src.tools.skills import (
    SkillLoader,
    list_skills,
    invoke_skill,
    run_skill_chain,
)


# ---------------------------------------------------------------------------
# Test skill file contents
# ---------------------------------------------------------------------------

SKILL_GENERAL_NO_PARAMS = """\
---
name: General Helper
triggers: [help, assist]
description: A general-purpose helper skill
category: general
chain_compatible: true
version: "2.0"
---
Hello {context}. I am here to help.
"""

SKILL_RESEARCH_WITH_PARAM = """\
---
name: Research Deep
triggers: [research, investigate]
description: Performs deep research on a topic
category: research
chain_compatible: true
version: "2.0"
params:
  - name: depth
    description: How deep to research
    required: false
    default: standard
---
Research {context} at {depth} level.
"""

SKILL_NON_CHAINABLE = """\
---
name: Solo Runner
triggers: [solo, standalone]
description: A skill that cannot be chained
category: productivity
chain_compatible: false
version: "2.0"
---
Run solo on {context}.
"""


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

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
    """Patch the module-level _default_loader so tool functions use our test loader."""
    monkeypatch.setattr("src.tools.skills._default_loader", loader)


@pytest.fixture
def populated_dir(skills_dir: Path) -> Path:
    """Write all three test skill files and return the skills dir."""
    _write_skill(skills_dir, "general_helper.md", SKILL_GENERAL_NO_PARAMS)
    _write_skill(skills_dir, "research_deep.md", SKILL_RESEARCH_WITH_PARAM)
    _write_skill(skills_dir, "solo_runner.md", SKILL_NON_CHAINABLE)
    return skills_dir


# ===========================================================================
# list_skills tests (edge cases beyond test_list_skills.py)
# ===========================================================================

class TestListSkillsEdgeCases:
    """Edge cases for list_skills not covered in test_list_skills.py."""

    def test_multiple_skills_same_category_grouped(self, populated_dir):
        """Two skills in different categories appear under correct headers."""
        result = list_skills.invoke({})
        assert "📂 general:" in result
        assert "📂 research:" in result
        assert "📂 productivity:" in result

    def test_category_filter_case_sensitive(self, populated_dir):
        """Category filter is exact-match (case-sensitive)."""
        result = list_skills.invoke({"category": "Research"})
        # Our implementation uses exact match, so uppercase won't match
        assert "No skills found in category 'Research'." == result

    def test_empty_string_category_returns_all(self, populated_dir):
        """Empty string category returns all skills grouped."""
        result = list_skills.invoke({"category": ""})
        assert "📚 Available Skills:" in result
        assert "General Helper" in result
        assert "Research Deep" in result

    def test_single_skill_loaded(self, skills_dir):
        """Only one skill file present."""
        _write_skill(skills_dir, "only.md", SKILL_GENERAL_NO_PARAMS)
        result = list_skills.invoke({})
        assert "General Helper" in result
        assert "📂 general:" in result


# ===========================================================================
# invoke_skill tests
# ===========================================================================

class TestInvokeSkillValid:
    """invoke_skill with valid skill name and params. Req 7.1, 7.2"""

    def test_basic_invocation_no_params(self, populated_dir):
        result = invoke_skill.invoke({"skill_name": "General Helper", "context": "world"})
        assert result.startswith("[Skill: General Helper]")
        assert "Hello world" in result

    def test_invocation_with_valid_json_params(self, populated_dir):
        result = invoke_skill.invoke({
            "skill_name": "Research Deep",
            "context": "AI trends",
            "params": '{"depth": "deep"}',
        })
        assert "[Skill: Research Deep]" in result
        assert "Research AI trends at deep level" in result

    def test_default_param_applied_when_omitted(self, populated_dir):
        result = invoke_skill.invoke({
            "skill_name": "Research Deep",
            "context": "AI trends",
        })
        assert "Research AI trends at standard level" in result

    def test_empty_context(self, populated_dir):
        result = invoke_skill.invoke({"skill_name": "General Helper", "context": ""})
        assert "[Skill: General Helper]" in result
        assert "Hello " in result


class TestInvokeSkillInvalidJSON:
    """invoke_skill with invalid JSON params. Req 7.3"""

    def test_malformed_json_returns_error(self, populated_dir):
        result = invoke_skill.invoke({
            "skill_name": "Research Deep",
            "context": "test",
            "params": "{not valid json}",
        })
        assert "Invalid params JSON" in result

    def test_non_json_string_returns_error(self, populated_dir):
        result = invoke_skill.invoke({
            "skill_name": "Research Deep",
            "context": "test",
            "params": "just a string",
        })
        assert "Invalid params JSON" in result


class TestInvokeSkillMissingRequiredParams:
    """invoke_skill with missing required params. Req 7.5"""

    def test_missing_required_param_returns_error(self, skills_dir):
        skill_with_required = """\
---
name: Strict Skill
triggers: [strict]
description: Needs a required param
category: general
params:
  - name: mode
    description: Operating mode
    required: true
---
Run in {mode} mode on {context}.
"""
        _write_skill(skills_dir, "strict.md", skill_with_required)
        result = invoke_skill.invoke({
            "skill_name": "Strict Skill",
            "context": "data",
        })
        assert "Parameter error" in result
        assert "mode" in result


class TestInvokeSkillUnknown:
    """invoke_skill with unknown skill name. Req 7.4"""

    def test_unknown_skill_returns_error_with_available(self, populated_dir):
        result = invoke_skill.invoke({"skill_name": "Nonexistent Skill"})
        assert "not found" in result
        assert "Available:" in result
        assert "General Helper" in result
        assert "Research Deep" in result

    def test_unknown_skill_empty_registry(self):
        """No skills loaded at all."""
        result = invoke_skill.invoke({"skill_name": "Anything"})
        assert "not found" in result
        assert "Available: none" in result


class TestInvokeSkillContextInjection:
    """invoke_skill context injection replaces placeholders. Req 7.1"""

    def test_context_placeholder_replaced(self, populated_dir):
        result = invoke_skill.invoke({
            "skill_name": "General Helper",
            "context": "my special context",
        })
        assert "my special context" in result
        assert "{context}" not in result

    def test_param_placeholder_replaced(self, populated_dir):
        result = invoke_skill.invoke({
            "skill_name": "Research Deep",
            "context": "topic",
            "params": '{"depth": "quick"}',
        })
        assert "quick" in result
        assert "{depth}" not in result


# ===========================================================================
# run_skill_chain tests
# ===========================================================================

class TestRunSkillChainValid:
    """run_skill_chain with valid chains. Req 8.1, 8.2"""

    def test_single_step_chain(self, populated_dir):
        result = run_skill_chain.invoke({
            "steps": "General Helper",
            "context": "world",
        })
        assert "[Skill Chain: 1 steps]" in result
        assert "Hello world" in result

    def test_two_step_chain(self, populated_dir):
        result = run_skill_chain.invoke({
            "steps": "General Helper, Research Deep",
            "context": "AI",
        })
        assert "[Skill Chain: 2 steps]" in result
        assert "Step 1: General Helper" in result
        assert "Step 2: Research Deep" in result
        assert "Hello AI" in result
        assert "Research AI" in result

    def test_chain_continuation_context_in_second_step(self, populated_dir):
        result = run_skill_chain.invoke({
            "steps": "General Helper, Research Deep",
            "context": "data",
        })
        assert "[Chain Step 2/2" in result
        assert "Previous: General Helper" in result


class TestRunSkillChainInvalidSkill:
    """run_skill_chain with invalid skill names. Req 8.3"""

    def test_nonexistent_skill_returns_error(self, populated_dir):
        result = run_skill_chain.invoke({
            "steps": "Nonexistent Skill",
            "context": "test",
        })
        assert "Chain error" in result
        assert "Skill not found" in result

    def test_non_chain_compatible_returns_error(self, populated_dir):
        result = run_skill_chain.invoke({
            "steps": "Solo Runner",
            "context": "test",
        })
        assert "Chain error" in result
        assert "not chain-compatible" in result


class TestRunSkillChainEmptySteps:
    """run_skill_chain with empty steps string. Req 8.4"""

    def test_empty_string_returns_error(self, populated_dir):
        result = run_skill_chain.invoke({"steps": ""})
        assert "Please provide at least one skill name" in result

    def test_whitespace_only_returns_error(self, populated_dir):
        result = run_skill_chain.invoke({"steps": "   "})
        assert "Please provide at least one skill name" in result

    def test_commas_only_returns_error(self, populated_dir):
        result = run_skill_chain.invoke({"steps": ",,,"})
        assert "Please provide at least one skill name" in result


class TestRunSkillChainTooManySteps:
    """run_skill_chain with >5 steps. Req 8.3 (chain length bound)"""

    def test_six_steps_returns_error(self, populated_dir):
        six_steps = ", ".join(["General Helper"] * 6)
        result = run_skill_chain.invoke({"steps": six_steps, "context": "test"})
        assert "Chain error" in result
        assert "Chain too long" in result
