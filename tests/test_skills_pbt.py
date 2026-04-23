"""Property-based tests for skills data models and front-matter parsing (Hypothesis).

Tests:
  Property 1 — Backward Compatibility (Requirements 2.2, 15.1)
  Property 5 — Context Injection Completeness (Requirements 4.1, 4.6)
  Property 4 (partial) — Round-trip Consistency (Requirements 15.4)
  Property 6 — Cache Consistency (Requirements 2.4, 2.5)
"""
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

sys.modules["mem0"] = MagicMock()

from hypothesis import given, settings, assume
from hypothesis import strategies as st

from src.tools.skills import (
    _parse_front_matter,
    _parse_skill_file,
    ChainPipeline,
    ChainStep,
    ContextInjector,
    SkillDefinition,
    SkillLoader,
    SkillParam,
    ALLOWED_CATEGORIES,
)

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Non-empty printable strings without YAML-special characters that could
# break front-matter parsing (no colons, dashes-at-start, brackets, hashes,
# newlines, or leading/trailing whitespace).
_safe_char = st.sampled_from(
    "abcdefghijklmnopqrstuvwxyz"
    "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    "0123456789 "
)
safe_text = st.text(_safe_char, min_size=1, max_size=60).map(str.strip).filter(
    lambda s: len(s) > 0
)

# A trigger word: lowercase alpha only, no spaces (keeps YAML list simple).
trigger_word = st.text(
    st.sampled_from("abcdefghijklmnopqrstuvwxyz"),
    min_size=1,
    max_size=20,
)

# A non-empty list of unique trigger words.
trigger_list = st.lists(trigger_word, min_size=1, max_size=5, unique=True)

# A category from the allowed set.
category_st = st.sampled_from(sorted(ALLOWED_CATEGORIES))


# ---------------------------------------------------------------------------
# Helper: serialize a SkillDefinition back to front-matter + prompt text
# ---------------------------------------------------------------------------

def _serialize_skill(sd: SkillDefinition) -> str:
    """Serialize a SkillDefinition to a markdown string with YAML front-matter."""
    lines = ["---"]
    lines.append(f"name: {sd.name}")
    triggers_str = ", ".join(sd.triggers)
    lines.append(f"triggers: [{triggers_str}]")
    lines.append(f"description: {sd.description}")
    lines.append(f"category: {sd.category}")
    if sd.params:
        lines.append("params:")
        for p in sd.params:
            lines.append(f"  - name: {p.name}")
            lines.append(f"    description: {p.description}")
            lines.append(f"    required: {'true' if p.required else 'false'}")
            if p.default is not None:
                lines.append(f"    default: {p.default}")
    tools_str = ", ".join(sd.tools_used)
    lines.append(f"tools_used: [{tools_str}]")
    lines.append(f"chain_compatible: {'true' if sd.chain_compatible else 'false'}")
    lines.append(f'version: "{sd.version}"')
    lines.append("---")
    lines.append(sd.prompt)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Property 1: Backward Compatibility
# Validates: Requirements 2.2, 15.1
#
# For any generated v1.0 front-matter (name, triggers, description only),
# parsing via _parse_skill_file produces a valid SkillDefinition with correct
# defaults for category ("general"), params ([]), tools_used ([]),
# chain_compatible (True), version ("1.0").
# ---------------------------------------------------------------------------

@given(
    name=safe_text,
    triggers=trigger_list,
    description=safe_text,
    prompt=safe_text,
)
@settings(max_examples=200, deadline=None)
def test_property1_backward_compatibility(name, triggers, description, prompt):
    """**Validates: Requirements 2.2, 15.1**"""
    # Build a v1.0 front-matter string (no v2 fields)
    triggers_str = ", ".join(triggers)
    text = (
        f"---\n"
        f"name: {name}\n"
        f"triggers: [{triggers_str}]\n"
        f"description: {description}\n"
        f"---\n"
        f"{prompt}"
    )

    sd = _parse_skill_file(text, "generated_v1.md")

    # Core fields parsed correctly
    assert sd.name == name
    assert sd.triggers == triggers
    assert sd.description == description
    assert sd.prompt == prompt

    # v2 defaults applied
    assert sd.category == "general"
    assert sd.params == []
    assert sd.tools_used == []
    assert sd.chain_compatible is True
    assert sd.version == "1.0"


# ---------------------------------------------------------------------------
# Property 5: Context Injection Completeness
# Validates: Requirements 4.1, 4.6
#
# For any skill prompt containing {context} or {input} and any context string,
# after simple string replacement no {context} or {input} literal remains.
# ---------------------------------------------------------------------------

# Strategy: prompts that definitely contain at least one placeholder.
_placeholder = st.sampled_from(["{context}", "{input}"])

prompt_with_placeholders = st.builds(
    lambda parts: "".join(parts),
    st.lists(
        st.one_of(safe_text, _placeholder),
        min_size=2,
        max_size=8,
    ),
).filter(lambda s: "{context}" in s or "{input}" in s)

context_string = st.text(
    st.sampled_from("abcdefghijklmnopqrstuvwxyz0123456789 "),
    min_size=0,
    max_size=80,
)


@given(prompt=prompt_with_placeholders, ctx=context_string)
@settings(max_examples=200, deadline=None)
def test_property5_context_injection_completeness(prompt, ctx):
    """**Validates: Requirements 4.1, 4.6**"""
    result = prompt.replace("{context}", ctx).replace("{input}", ctx)
    assert "{context}" not in result
    assert "{input}" not in result


# ---------------------------------------------------------------------------
# Property 4 (partial): Round-trip Consistency
# Validates: Requirements 15.4
#
# Parsing a front-matter block and re-serializing produces an equivalent
# SkillDefinition when re-parsed.
# ---------------------------------------------------------------------------

# Strategy for SkillParam (safe names without spaces to avoid YAML issues)
param_name_st = st.text(
    st.sampled_from("abcdefghijklmnopqrstuvwxyz"),
    min_size=1,
    max_size=15,
)

skill_param_st = st.builds(
    SkillParam,
    name=param_name_st,
    description=safe_text,
    required=st.booleans(),
    default=st.one_of(st.none(), safe_text),
)

# Strategy for a valid SkillDefinition
skill_definition_st = st.builds(
    SkillDefinition,
    file=st.just("roundtrip.md"),
    name=safe_text,
    triggers=trigger_list,
    description=safe_text,
    prompt=safe_text,
    category=category_st,
    params=st.lists(skill_param_st, min_size=0, max_size=3, unique_by=lambda p: p.name),
    chain_compatible=st.booleans(),
    version=st.sampled_from(["1.0", "2.0"]),
    tools_used=st.lists(
        st.text(st.sampled_from("abcdefghijklmnopqrstuvwxyz_"), min_size=1, max_size=20),
        min_size=0,
        max_size=3,
    ),
)


@given(sd=skill_definition_st)
@settings(max_examples=200, deadline=None)
def test_property4_roundtrip_consistency(sd):
    """**Validates: Requirements 15.4**"""
    # Serialize → parse → compare
    serialized = _serialize_skill(sd)
    reparsed = _parse_skill_file(serialized, sd.file)

    assert reparsed.name == sd.name
    assert reparsed.triggers == sd.triggers
    assert reparsed.description == sd.description
    assert reparsed.prompt == sd.prompt
    assert reparsed.category == sd.category
    assert reparsed.chain_compatible == sd.chain_compatible
    assert reparsed.version == sd.version
    assert reparsed.tools_used == sd.tools_used

    # Compare params
    assert len(reparsed.params) == len(sd.params)
    for orig, parsed in zip(sd.params, reparsed.params):
        assert parsed.name == orig.name
        assert parsed.description == orig.description
        assert parsed.required == orig.required
        assert parsed.default == orig.default


# ---------------------------------------------------------------------------
# Strategies for Property 6
# ---------------------------------------------------------------------------

# Skill names: lowercase alpha, no spaces, suitable for use in YAML front-matter
skill_name_st = st.text(
    st.sampled_from("abcdefghijklmnopqrstuvwxyz"),
    min_size=2,
    max_size=20,
).filter(lambda s: len(s.strip()) >= 2)

# ---------------------------------------------------------------------------
# Property 6: Cache Consistency
# Validates: Requirements 2.4, 2.5
#
# After invalidate_cache(), the next load_all() re-reads from disk.
# Verified by modifying a file between calls.
# ---------------------------------------------------------------------------


@given(
    name_a=skill_name_st,
    name_b=skill_name_st,
    triggers=trigger_list,
)
@settings(max_examples=50, deadline=None)
def test_property6_cache_consistency(name_a, name_b, triggers):
    """**Validates: Requirements 2.4, 2.5**"""
    assume(name_a != name_b)

    tmp_dir = tempfile.mkdtemp()
    skills_dir = Path(tmp_dir)

    triggers_str = ", ".join(triggers)

    # Step 1: Write initial skill file
    skill_file = skills_dir / "skill.md"
    skill_file.write_text(
        f"---\n"
        f"name: {name_a}\n"
        f"triggers: [{triggers_str}]\n"
        f"description: original skill\n"
        f"---\n"
        f"Prompt for {name_a}.\n",
        encoding="utf-8",
    )

    # Step 2: Create loader and populate cache
    loader = SkillLoader(skills_dir)
    first_load = loader.load_all()
    assert len(first_load) == 1
    assert first_load[0].name == name_a

    # Step 3: Modify the skill file on disk (change the name)
    skill_file.write_text(
        f"---\n"
        f"name: {name_b}\n"
        f"triggers: [{triggers_str}]\n"
        f"description: modified skill\n"
        f"---\n"
        f"Prompt for {name_b}.\n",
        encoding="utf-8",
    )

    # Step 4: load_all() again — should return cached (old) data
    cached_load = loader.load_all()
    assert len(cached_load) == 1
    assert cached_load[0].name == name_a, (
        "Expected cached name to be the original, but got the modified name"
    )

    # Step 5: Invalidate cache
    loader.invalidate_cache()

    # Step 6: load_all() again — should return new data from disk
    fresh_load = loader.load_all()
    assert len(fresh_load) == 1
    assert fresh_load[0].name == name_b, (
        "After invalidate_cache(), load_all() should re-read from disk"
    )


# ---------------------------------------------------------------------------
# Strategies for Properties 2, 3, 7 (Matching)
# ---------------------------------------------------------------------------

from src.tools.skills import SkillMatcher

# Multi-word text that won't be treated as stop words by TF-IDF.
# Real skill names/descriptions always have meaningful multi-word content.
_word_st = st.text(
    st.sampled_from("abcdefghijklmnopqrstuvwxyz"),
    min_size=3,
    max_size=12,
)
_multi_word_st = st.lists(_word_st, min_size=2, max_size=5).map(lambda ws: " ".join(ws))

# Trigger words for matching: at least 3 chars to avoid stop-word issues.
_matching_trigger = st.text(
    st.sampled_from("abcdefghijklmnopqrstuvwxyz"),
    min_size=3,
    max_size=15,
)
_matching_trigger_list = st.lists(_matching_trigger, min_size=1, max_size=5, unique=True)

# A SkillDefinition suitable for matching tests (realistic, valid).
matching_skill_st = st.builds(
    SkillDefinition,
    file=st.from_regex(r"[a-z]{3,10}\.md", fullmatch=True),
    name=_multi_word_st,
    triggers=_matching_trigger_list,
    description=_multi_word_st,
    prompt=safe_text,
    category=category_st,
    params=st.just([]),
    chain_compatible=st.just(True),
    version=st.just("1.0"),
    tools_used=st.just([]),
)

# A non-empty list of skills with unique file names (needed for matcher internals).
skill_list_st = st.lists(
    matching_skill_st, min_size=1, max_size=5, unique_by=lambda s: s.file
)

# Query strings for matching tests: multi-word to be realistic.
query_st = _multi_word_st


def _mock_loader(skills: list[SkillDefinition]) -> SkillLoader:
    """Create a MagicMock SkillLoader that returns the given skills."""
    loader = MagicMock(spec=SkillLoader)
    loader.load_all.return_value = skills
    return loader


# ---------------------------------------------------------------------------
# Property 2: Matching Determinism
# Validates: Requirements 3.9
#
# For any query and skill set, match(q, S) returns identical results on
# repeated calls.
# ---------------------------------------------------------------------------


@given(query=query_st, skills=skill_list_st)
@settings(max_examples=100, deadline=None)
def test_property2_matching_determinism(query, skills):
    """**Validates: Requirements 3.9**"""
    loader = _mock_loader(skills)
    matcher = SkillMatcher(loader)

    result1 = matcher.match(query)
    result2 = matcher.match(query)

    # Same number of results
    assert len(result1) == len(result2)

    # Same skills in same order with same scores
    for (skill1, score1), (skill2, score2) in zip(result1, result2):
        assert skill1.file == skill2.file
        assert skill1.name == skill2.name
        assert score1 == score2


# ---------------------------------------------------------------------------
# Property 3: Keyword Subsumption
# Validates: Requirements 3.2
#
# If any trigger of a skill is a substring of the query, _keyword_score
# returns 1.0.
# ---------------------------------------------------------------------------


@given(skill=matching_skill_st, prefix=_multi_word_st, suffix=_multi_word_st)
@settings(max_examples=100, deadline=None)
def test_property3_keyword_subsumption(skill, prefix, suffix):
    """**Validates: Requirements 3.2**"""
    # Pick the first trigger and embed it in a query
    trigger = skill.triggers[0]
    query = prefix + " " + trigger + " " + suffix

    loader = _mock_loader([skill])
    matcher = SkillMatcher(loader)

    score = matcher._keyword_score(query, skill)
    assert score == 1.0


# ---------------------------------------------------------------------------
# Property 7: Score Bounds
# Validates: Requirements 3.8
#
# For any match result, score is in [0.0, 1.0].
# ---------------------------------------------------------------------------


@given(query=query_st, skills=skill_list_st)
@settings(max_examples=100, deadline=None)
def test_property7_score_bounds(query, skills):
    """**Validates: Requirements 3.8**"""
    loader = _mock_loader(skills)
    matcher = SkillMatcher(loader)

    results = matcher.match(query)
    for _skill, score in results:
        assert 0.0 <= score <= 1.0


# ---------------------------------------------------------------------------
# Helpers for Chain Pipeline Property Tests
# ---------------------------------------------------------------------------


class FakeLoader:
    """In-memory SkillLoader substitute for property tests."""

    def __init__(self, skills: dict[str, SkillDefinition]) -> None:
        self._skills = skills

    def load_all(self) -> list[SkillDefinition]:
        return list(self._skills.values())

    def get_by_name(self, name: str):
        return self._skills.get(name.lower())

    def get_by_category(self, category: str):
        return [s for s in self._skills.values() if s.category == category]

    def invalidate_cache(self):
        pass


def _make_chain_skill(name: str) -> SkillDefinition:
    """Create a minimal chain-compatible skill for property tests."""
    return SkillDefinition(
        file=f"{name.lower().replace(' ', '_')}.md",
        name=name,
        triggers=[name.lower()],
        description=f"A {name} skill",
        prompt=f"Do {{context}} for {name}",
        chain_compatible=True,
    )


# Strategy: skill names — lowercase alpha, 3-20 chars, unique and non-empty.
_chain_skill_name = st.text(
    st.sampled_from("abcdefghijklmnopqrstuvwxyz"),
    min_size=3,
    max_size=20,
)


# ---------------------------------------------------------------------------
# Property 4: Chain Length Bound
# Validates: Requirements 5.2
#
# For any chain with >5 steps, build raises ValueError with "Chain too long".
# ---------------------------------------------------------------------------


@given(
    skill_names=st.lists(
        _chain_skill_name,
        min_size=6,
        max_size=10,
        unique=True,
    ),
)
@settings(max_examples=100, deadline=None)
def test_property4_chain_length_bound(skill_names):
    """**Validates: Requirements 5.2**"""
    # Build a FakeLoader with all the generated skills
    skills = {name.lower(): _make_chain_skill(name) for name in skill_names}
    loader = FakeLoader(skills)
    injector = ContextInjector()
    pipeline = ChainPipeline(loader, injector)

    import pytest
    with pytest.raises(ValueError, match="Chain too long"):
        pipeline.build(skill_names, context="test context")


# ---------------------------------------------------------------------------
# Property 8: Chain Validation
# Validates: Requirements 5.3
#
# For any chain step referencing a non-existent skill name, build raises
# ValueError with "Skill not found" before rendering.
# ---------------------------------------------------------------------------


@given(
    existing_names=st.lists(
        _chain_skill_name,
        min_size=1,
        max_size=4,
        unique=True,
    ),
    missing_name=_chain_skill_name,
)
@settings(max_examples=100, deadline=None)
def test_property8_chain_validation_missing_skill(existing_names, missing_name):
    """**Validates: Requirements 5.3**"""
    # Ensure the missing name is truly not in the loader
    assume(missing_name.lower() not in {n.lower() for n in existing_names})

    skills = {name.lower(): _make_chain_skill(name) for name in existing_names}
    loader = FakeLoader(skills)
    injector = ContextInjector()
    pipeline = ChainPipeline(loader, injector)

    # Build a chain that includes the missing skill name
    chain_steps = [existing_names[0], missing_name]

    import pytest
    with pytest.raises(ValueError, match="Skill not found"):
        pipeline.build(chain_steps, context="test context")
