"""Unit tests for ChainStep, ChainResult, and ChainPipeline."""

import pytest

from src.tools.skills import (
    ChainPipeline,
    ChainResult,
    ChainStep,
    ContextInjector,
    SkillDefinition,
    SkillLoader,
    SkillParam,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_skill(
    name: str = "Test Skill",
    prompt: str = "Do {context}",
    chain_compatible: bool = True,
    params: list[SkillParam] | None = None,
) -> SkillDefinition:
    return SkillDefinition(
        file=f"{name.lower().replace(' ', '_')}.md",
        name=name,
        triggers=[name.lower()],
        description=f"A {name} skill",
        prompt=prompt,
        chain_compatible=chain_compatible,
        params=params or [],
    )


class FakeLoader:
    """In-memory SkillLoader substitute for unit tests."""

    def __init__(self, skills: list[SkillDefinition]) -> None:
        self._skills = {s.name.lower(): s for s in skills}

    def load_all(self) -> list[SkillDefinition]:
        return list(self._skills.values())

    def get_by_name(self, name: str):
        return self._skills.get(name.lower())

    def get_by_category(self, category: str):
        return [s for s in self._skills.values() if s.category == category]

    def invalidate_cache(self):
        pass


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def research_skill():
    return _make_skill(name="Research Assistant", prompt="Research {context}")


@pytest.fixture
def presentation_skill():
    return _make_skill(name="Presentation Builder", prompt="Present {context}")


@pytest.fixture
def non_chainable_skill():
    return _make_skill(name="Solo Skill", prompt="Solo {context}", chain_compatible=False)


@pytest.fixture
def param_skill():
    return _make_skill(
        name="Param Skill",
        prompt="Do {context} at {depth}",
        params=[SkillParam(name="depth", description="Depth", required=False, default="standard")],
    )


@pytest.fixture
def loader(research_skill, presentation_skill, non_chainable_skill, param_skill):
    return FakeLoader([research_skill, presentation_skill, non_chainable_skill, param_skill])


@pytest.fixture
def injector():
    return ContextInjector()


@pytest.fixture
def pipeline(loader, injector):
    return ChainPipeline(loader, injector)


# ---------------------------------------------------------------------------
# ChainStep dataclass tests
# ---------------------------------------------------------------------------

class TestChainStep:
    def test_defaults(self):
        step = ChainStep(skill_name="research")
        assert step.skill_name == "research"
        assert step.params == {}
        assert step.context_override is None

    def test_with_params_and_override(self):
        step = ChainStep(
            skill_name="research",
            params={"depth": "deep"},
            context_override="custom context",
        )
        assert step.params == {"depth": "deep"}
        assert step.context_override == "custom context"


# ---------------------------------------------------------------------------
# ChainResult dataclass tests
# ---------------------------------------------------------------------------

class TestChainResult:
    def test_fields(self):
        result = ChainResult(steps=["prompt1", "prompt2"], instructions="do stuff")
        assert result.steps == ["prompt1", "prompt2"]
        assert result.instructions == "do stuff"


# ---------------------------------------------------------------------------
# ChainPipeline.build tests
# ---------------------------------------------------------------------------

class TestChainPipelineBuild:
    def test_single_step_string(self, pipeline):
        result = pipeline.build(["Research Assistant"], context="AI trends")
        assert len(result.steps) == 1
        assert "Research AI trends" in result.steps[0]
        assert "[Skill Chain: 1 steps]" in result.instructions
        assert "Step 1: Research Assistant" in result.instructions

    def test_two_step_chain(self, pipeline):
        result = pipeline.build(
            ["Research Assistant", "Presentation Builder"],
            context="AI trends",
        )
        assert len(result.steps) == 2
        # First step: no chain header
        assert not result.steps[0].startswith("[Chain Step")
        assert "Research AI trends" in result.steps[0]
        # Second step: has chain header
        assert result.steps[1].startswith("[Chain Step 2/2")
        assert "Present AI trends" in result.steps[1]

    def test_chain_instructions_format(self, pipeline):
        result = pipeline.build(
            ["Research Assistant", "Presentation Builder"],
            context="data",
        )
        assert "[Skill Chain: 2 steps]" in result.instructions
        assert "Step 1: Research Assistant" in result.instructions
        assert "Step 2: Presentation Builder" in result.instructions
        assert "Complete each step fully before moving to the next." in result.instructions

    def test_string_steps_normalized_to_chainstep(self, pipeline):
        result = pipeline.build(["Research Assistant"], context="test")
        assert len(result.steps) == 1

    def test_chainstep_objects_accepted(self, pipeline):
        steps = [
            ChainStep(skill_name="Research Assistant"),
            ChainStep(skill_name="Presentation Builder"),
        ]
        result = pipeline.build(steps, context="test")
        assert len(result.steps) == 2

    def test_context_override_per_step(self, pipeline):
        steps = [
            ChainStep(skill_name="Research Assistant"),
            ChainStep(skill_name="Presentation Builder", context_override="custom topic"),
        ]
        result = pipeline.build(steps, context="original")
        assert "Research original" in result.steps[0]
        assert "Present custom topic" in result.steps[1]

    def test_params_passed_to_injector(self, pipeline):
        steps = [
            ChainStep(skill_name="Param Skill", params={"depth": "deep"}),
        ]
        result = pipeline.build(steps, context="stuff")
        assert "Do stuff at deep" in result.steps[0]

    def test_default_params_applied(self, pipeline):
        steps = [ChainStep(skill_name="Param Skill")]
        result = pipeline.build(steps, context="stuff")
        assert "Do stuff at standard" in result.steps[0]

    def test_max_five_steps_allowed(self, pipeline, loader):
        # Add more skills so we have 5 chainable ones
        loader._skills["skill a"] = _make_skill(name="Skill A", prompt="A {context}")
        loader._skills["skill b"] = _make_skill(name="Skill B", prompt="B {context}")
        loader._skills["skill c"] = _make_skill(name="Skill C", prompt="C {context}")
        result = pipeline.build(
            ["Research Assistant", "Presentation Builder", "Skill A", "Skill B", "Skill C"],
            context="test",
        )
        assert len(result.steps) == 5

    def test_chain_continuation_context_in_later_steps(self, pipeline):
        result = pipeline.build(
            ["Research Assistant", "Presentation Builder"],
            context="data",
        )
        # Step 2 should have chain header with previous step info
        assert "[Chain Step 2/2 — Previous: Research Assistant]" in result.steps[1]
        assert "Use the output from the previous step(s) as input for this step." in result.steps[1]


# ---------------------------------------------------------------------------
# ChainPipeline.build error cases
# ---------------------------------------------------------------------------

class TestChainPipelineBuildErrors:
    def test_raises_if_chain_exceeds_max_length(self, pipeline):
        with pytest.raises(ValueError, match="Chain too long"):
            pipeline.build(["Research Assistant"] * 6, context="test")

    def test_raises_if_skill_not_found(self, pipeline):
        with pytest.raises(ValueError, match="Skill not found: Nonexistent"):
            pipeline.build(["Nonexistent"], context="test")

    def test_raises_if_skill_not_chain_compatible(self, pipeline):
        with pytest.raises(ValueError, match="not chain-compatible: Solo Skill"):
            pipeline.build(["Solo Skill"], context="test")

    def test_raises_before_rendering_on_invalid_skill(self, pipeline):
        """Validation errors should be raised before any rendering happens."""
        with pytest.raises(ValueError, match="Skill not found"):
            pipeline.build(
                ["Research Assistant", "Does Not Exist"],
                context="test",
            )

    def test_multiple_errors_joined(self, pipeline):
        with pytest.raises(ValueError, match="Skill not found: A.*Skill not found: B"):
            pipeline.build(["A", "B"], context="test")

    def test_mixed_not_found_and_not_compatible(self, pipeline):
        with pytest.raises(ValueError) as exc_info:
            pipeline.build(["Missing Skill", "Solo Skill"], context="test")
        msg = str(exc_info.value)
        assert "Skill not found: Missing Skill" in msg
        assert "not chain-compatible: Solo Skill" in msg


# ---------------------------------------------------------------------------
# ChainPipeline.validate_chain tests
# ---------------------------------------------------------------------------

class TestValidateChain:
    def test_valid_chain_returns_empty(self, pipeline):
        errors = pipeline.validate_chain(["Research Assistant", "Presentation Builder"])
        assert errors == []

    def test_missing_skill_returns_error(self, pipeline):
        errors = pipeline.validate_chain(["Nonexistent"])
        assert len(errors) == 1
        assert "Skill not found: Nonexistent" in errors[0]

    def test_not_chain_compatible_returns_error(self, pipeline):
        errors = pipeline.validate_chain(["Solo Skill"])
        assert len(errors) == 1
        assert "not chain-compatible" in errors[0]

    def test_too_long_chain_returns_error(self, pipeline):
        errors = pipeline.validate_chain(["Research Assistant"] * 6)
        assert any("Chain too long" in e for e in errors)

    def test_multiple_errors_returned(self, pipeline):
        errors = pipeline.validate_chain(["Missing", "Solo Skill"])
        assert len(errors) == 2
