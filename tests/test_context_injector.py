"""Unit tests for ContextInjector class."""

import pytest

from src.tools.skills import ContextInjector, SkillDefinition, SkillParam


def _make_skill(
    prompt: str = "Do the thing with {context}",
    params: list[SkillParam] | None = None,
    name: str = "Test Skill",
) -> SkillDefinition:
    """Helper to create a minimal SkillDefinition for testing."""
    return SkillDefinition(
        file="test_skill.md",
        name=name,
        triggers=["test"],
        description="A test skill",
        prompt=prompt,
        params=params or [],
    )


@pytest.fixture
def injector():
    return ContextInjector()


class TestInjectBasic:
    """Tests for basic context/input placeholder replacement."""

    def test_replaces_context_placeholder(self, injector):
        skill = _make_skill(prompt="Analyze {context} carefully")
        result = injector.inject(skill, "some data")
        assert result == "Analyze some data carefully"

    def test_replaces_input_placeholder(self, injector):
        skill = _make_skill(prompt="Process {input} now")
        result = injector.inject(skill, "user input")
        assert result == "Process user input now"

    def test_replaces_both_context_and_input(self, injector):
        skill = _make_skill(prompt="Use {context} and also {input}")
        result = injector.inject(skill, "data")
        assert result == "Use data and also data"

    def test_no_context_or_input_literals_remain(self, injector):
        skill = _make_skill(prompt="{context} is here and {input} too")
        result = injector.inject(skill, "replaced")
        assert "{context}" not in result
        assert "{input}" not in result

    def test_empty_context_replaces_placeholders(self, injector):
        skill = _make_skill(prompt="Before {context} after")
        result = injector.inject(skill, "")
        assert result == "Before  after"
        assert "{context}" not in result

    def test_prompt_without_placeholders_unchanged(self, injector):
        skill = _make_skill(prompt="No placeholders here")
        result = injector.inject(skill, "anything")
        assert result == "No placeholders here"


class TestInjectParams:
    """Tests for named parameter placeholder replacement."""

    def test_replaces_param_placeholder(self, injector):
        skill = _make_skill(
            prompt="Chart type: {chart_type}",
            params=[SkillParam(name="chart_type", description="Type of chart", required=False, default="bar")],
        )
        result = injector.inject(skill, "", params={"chart_type": "pie"})
        assert result == "Chart type: pie"

    def test_applies_default_for_missing_optional_param(self, injector):
        skill = _make_skill(
            prompt="Depth: {depth}",
            params=[SkillParam(name="depth", description="Research depth", required=False, default="standard")],
        )
        result = injector.inject(skill, "")
        assert result == "Depth: standard"

    def test_multiple_params_replaced(self, injector):
        skill = _make_skill(
            prompt="{context} with {style} and {tone}",
            params=[
                SkillParam(name="style", description="Writing style", required=True),
                SkillParam(name="tone", description="Writing tone", required=True),
            ],
        )
        result = injector.inject(skill, "text", params={"style": "formal", "tone": "friendly"})
        assert result == "text with formal and friendly"


class TestValidateParams:
    """Tests for _validate_params."""

    def test_raises_for_missing_required_param(self, injector):
        skill = _make_skill(
            params=[SkillParam(name="depth", description="Research depth", required=True)],
        )
        with pytest.raises(ValueError, match="depth"):
            injector._validate_params(skill, {})

    def test_error_message_includes_param_name(self, injector):
        skill = _make_skill(
            params=[SkillParam(name="my_param", description="Important param", required=True)],
        )
        with pytest.raises(ValueError, match="my_param"):
            injector._validate_params(skill, {})

    def test_applies_defaults_for_optional_params(self, injector):
        skill = _make_skill(
            params=[SkillParam(name="depth", description="Depth", required=False, default="standard")],
        )
        result = injector._validate_params(skill, {})
        assert result == {"depth": "standard"}

    def test_provided_params_override_defaults(self, injector):
        skill = _make_skill(
            params=[SkillParam(name="depth", description="Depth", required=False, default="standard")],
        )
        result = injector._validate_params(skill, {"depth": "deep"})
        assert result == {"depth": "deep"}

    def test_returns_completed_dict(self, injector):
        skill = _make_skill(
            params=[
                SkillParam(name="a", description="A", required=True),
                SkillParam(name="b", description="B", required=False, default="default_b"),
            ],
        )
        result = injector._validate_params(skill, {"a": "val_a"})
        assert result == {"a": "val_a", "b": "default_b"}

    def test_no_params_skill_returns_empty(self, injector):
        skill = _make_skill(params=[])
        result = injector._validate_params(skill, {})
        assert result == {}


class TestApplyChainContext:
    """Tests for _apply_chain_context."""

    def test_prepends_chain_header(self, injector):
        chain_state = {
            "current_step": 2,
            "step_count": 3,
            "previous_steps": ["Research Assistant"],
        }
        result = injector._apply_chain_context("Do something", chain_state)
        assert result.startswith("[Chain Step 2/3")
        assert "Research Assistant" in result
        assert result.endswith("Do something")

    def test_chain_header_format(self, injector):
        chain_state = {
            "current_step": 3,
            "step_count": 4,
            "previous_steps": ["Step A", "Step B"],
        }
        result = injector._apply_chain_context("prompt", chain_state)
        assert "[Chain Step 3/4 — Previous: Step A, Step B]" in result
        assert "Use the output from the previous step(s) as input for this step." in result

    def test_chain_header_with_single_previous(self, injector):
        chain_state = {
            "current_step": 2,
            "step_count": 2,
            "previous_steps": ["Only Step"],
        }
        result = injector._apply_chain_context("my prompt", chain_state)
        assert "[Chain Step 2/2 — Previous: Only Step]" in result


class TestInjectWithChainState:
    """Tests for inject with chain_state integration."""

    def test_chain_state_prepends_header(self, injector):
        skill = _make_skill(prompt="Analyze {context}")
        chain_state = {
            "current_step": 2,
            "step_count": 3,
            "previous_steps": ["Research"],
        }
        result = injector.inject(skill, "data", chain_state=chain_state)
        assert result.startswith("[Chain Step 2/3")
        assert "Analyze data" in result

    def test_no_chain_state_no_header(self, injector):
        skill = _make_skill(prompt="Analyze {context}")
        result = injector.inject(skill, "data")
        assert not result.startswith("[Chain Step")
        assert result == "Analyze data"

    def test_empty_previous_steps_no_header(self, injector):
        skill = _make_skill(prompt="Analyze {context}")
        chain_state = {
            "current_step": 1,
            "step_count": 2,
            "previous_steps": [],
        }
        result = injector.inject(skill, "data", chain_state=chain_state)
        assert not result.startswith("[Chain Step")

    def test_full_inject_with_params_and_chain(self, injector):
        skill = _make_skill(
            prompt="Research {context} at {depth} level",
            params=[SkillParam(name="depth", description="Depth", required=False, default="standard")],
        )
        chain_state = {
            "current_step": 2,
            "step_count": 3,
            "previous_steps": ["Scanner"],
        }
        result = injector.inject(skill, "AI trends", params={"depth": "deep"}, chain_state=chain_state)
        assert "[Chain Step 2/3" in result
        assert "Research AI trends at deep level" in result
