"""Unit tests for SkillMatcher class."""

import pytest
from pathlib import Path
from unittest.mock import MagicMock

from src.tools.skills import SkillDefinition, SkillLoader, SkillMatcher


def _make_skill(name: str, triggers: list[str], description: str = "", file: str = "") -> SkillDefinition:
    """Helper to create a minimal SkillDefinition for testing."""
    return SkillDefinition(
        file=file or f"{name.lower().replace(' ', '_')}.md",
        name=name,
        triggers=triggers,
        description=description or f"A skill for {name.lower()}",
        prompt="Do the thing with {context}",
    )


@pytest.fixture
def mock_loader():
    """Create a mock SkillLoader with a few test skills."""
    loader = MagicMock(spec=SkillLoader)
    skills = [
        _make_skill("Research Assistant", ["research", "investigate"], "Source-backed research"),
        _make_skill("Data Visualization", ["chart", "graph", "plot", "visualize"], "Create charts and graphs"),
        _make_skill("Email Drafter", ["email", "draft email", "compose email"], "Draft professional emails"),
    ]
    loader.load_all.return_value = skills
    return loader


@pytest.fixture
def matcher(mock_loader):
    return SkillMatcher(mock_loader)


class TestKeywordScore:
    """Tests for SkillMatcher._keyword_score."""

    def test_exact_substring_match_returns_1(self, matcher):
        skill = _make_skill("Research", ["research", "investigate"])
        assert matcher._keyword_score("I want to research AI", skill) == 1.0

    def test_exact_substring_case_insensitive(self, matcher):
        skill = _make_skill("Research", ["research"])
        assert matcher._keyword_score("RESEARCH this topic", skill) == 1.0

    def test_multi_word_trigger_substring(self, matcher):
        skill = _make_skill("Email", ["draft email"])
        assert matcher._keyword_score("please draft email for me", skill) == 1.0

    def test_partial_token_overlap(self, matcher):
        skill = _make_skill("Research", ["deep research analysis"])
        # "research" token overlaps, but "deep research analysis" is not a substring of "help me research"
        score = matcher._keyword_score("help me research", skill)
        assert 0.0 < score < 1.0

    def test_no_overlap_returns_0(self, matcher):
        skill = _make_skill("Research", ["research", "investigate"])
        assert matcher._keyword_score("make me a sandwich", skill) == 0.0

    def test_partial_overlap_ratio(self, matcher):
        # triggers: ["data analysis report"] → tokens: {data, analysis, report}
        skill = _make_skill("Analyzer", ["data analysis report"])
        # query tokens: {show, me, data} → overlap: {data} → 0.5 * 1/3
        score = matcher._keyword_score("show me data", skill)
        assert score == pytest.approx(0.5 * 1 / 3, abs=0.01)


class TestMatch:
    """Tests for SkillMatcher.match."""

    def test_returns_matches_sorted_by_score(self, matcher):
        results = matcher.match("research this topic")
        assert len(results) > 0
        scores = [score for _, score in results]
        assert scores == sorted(scores, reverse=True)

    def test_respects_top_k(self, matcher):
        results = matcher.match("help me with something", top_k=1)
        assert len(results) <= 1

    def test_empty_skills_returns_empty(self):
        loader = MagicMock(spec=SkillLoader)
        loader.load_all.return_value = []
        m = SkillMatcher(loader)
        assert m.match("anything") == []

    def test_exact_trigger_match_scores_high(self, matcher):
        results = matcher.match("research")
        # "research" is an exact trigger substring → keyword score 1.0
        if results:
            skill, score = results[0]
            assert skill.name == "Research Assistant"
            assert score >= 0.6  # at least keyword weight

    def test_scores_in_valid_range(self, matcher):
        results = matcher.match("research data visualization email")
        for _, score in results:
            assert 0.0 <= score <= 1.0


class TestMatchBest:
    """Tests for SkillMatcher.match_best."""

    def test_returns_best_match_above_threshold(self, matcher):
        result = matcher.match_best("research this topic")
        assert result is not None
        assert result.name == "Research Assistant"

    def test_returns_none_below_threshold(self):
        loader = MagicMock(spec=SkillLoader)
        loader.load_all.return_value = [
            _make_skill("Niche Skill", ["xyzzy_unique_trigger_42"])
        ]
        m = SkillMatcher(loader)
        result = m.match_best("completely unrelated query", threshold=0.9)
        assert result is None

    def test_returns_none_for_empty_skills(self):
        loader = MagicMock(spec=SkillLoader)
        loader.load_all.return_value = []
        m = SkillMatcher(loader)
        assert m.match_best("anything") is None


class TestSemanticScore:
    """Tests for SkillMatcher._semantic_score."""

    def test_returns_scores_for_all_skills(self, matcher):
        results = matcher._semantic_score("research data")
        # Should have one entry per skill
        assert len(results) == 3

    def test_scores_are_non_negative(self, matcher):
        results = matcher._semantic_score("chart visualization")
        for _, score in results:
            assert score >= 0.0


class TestRebuildIndex:
    """Tests for SkillMatcher._rebuild_index."""

    def test_builds_index_from_skills(self, matcher):
        matcher._rebuild_index()
        assert matcher._tfidf_matrix is not None
        assert matcher._vectorizer is not None
        assert len(matcher._skill_names) == 3

    def test_empty_skills_clears_index(self):
        loader = MagicMock(spec=SkillLoader)
        loader.load_all.return_value = []
        m = SkillMatcher(loader)
        m._rebuild_index()
        assert m._tfidf_matrix is None
        assert m._vectorizer is None
        assert m._skill_names == []
