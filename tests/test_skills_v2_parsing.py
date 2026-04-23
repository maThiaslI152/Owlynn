"""Tests for v2.0 front-matter parsing and _parse_skill_file helper."""
import sys
from unittest.mock import MagicMock
sys.modules["mem0"] = MagicMock()

import pytest
from src.tools.skills import (
    _parse_front_matter,
    _parse_skill_file,
    SkillDefinition,
    SkillParam,
)


# ---------------------------------------------------------------------------
# _parse_front_matter: structured params block
# ---------------------------------------------------------------------------

V2_FULL = """\
---
name: Research Assistant
triggers: [research, investigate, deep dive]
description: Source-backed research
category: research
params:
  - name: depth
    description: How deep to research
    required: false
    default: standard
  - name: format
    description: Output format
    required: true
tools_used: [web_search, fetch_webpage]
chain_compatible: true
version: "2.0"
---
Do the research on: {context}"""


def test_parse_v2_params_block():
    meta, body = _parse_front_matter(V2_FULL)
    assert isinstance(meta["params"], list)
    assert len(meta["params"]) == 2
    assert meta["params"][0]["name"] == "depth"
    assert meta["params"][0]["required"] == "false"
    assert meta["params"][0]["default"] == "standard"
    assert meta["params"][1]["name"] == "format"
    assert meta["params"][1]["required"] == "true"
    assert "default" not in meta["params"][1]


def test_parse_v2_tools_used_list():
    meta, _ = _parse_front_matter(V2_FULL)
    assert meta["tools_used"] == ["web_search", "fetch_webpage"]


def test_parse_v2_chain_compatible_true():
    meta, _ = _parse_front_matter(V2_FULL)
    assert meta["chain_compatible"] is True


def test_parse_v2_chain_compatible_false():
    text = """\
---
name: Solo Skill
triggers: [solo]
description: Not chainable
chain_compatible: false
---
Prompt body."""
    meta, _ = _parse_front_matter(text)
    assert meta["chain_compatible"] is False


def test_parse_v2_category():
    meta, _ = _parse_front_matter(V2_FULL)
    assert meta["category"] == "research"


def test_parse_v2_version():
    meta, _ = _parse_front_matter(V2_FULL)
    assert meta["version"] == "2.0"


def test_parse_v2_body_preserved():
    _, body = _parse_front_matter(V2_FULL)
    assert body == "Do the research on: {context}"


# ---------------------------------------------------------------------------
# _parse_front_matter: backward compatibility with v1.0
# ---------------------------------------------------------------------------

V1_SIMPLE = """\
---
name: Morning Briefing
triggers: [briefing, morning]
description: Daily briefing
---
Good morning!"""


def test_parse_v1_still_works():
    meta, body = _parse_front_matter(V1_SIMPLE)
    assert meta["name"] == "Morning Briefing"
    assert meta["triggers"] == ["briefing", "morning"]
    assert body == "Good morning!"
    # v2 fields should be absent
    assert "params" not in meta
    assert "category" not in meta


# ---------------------------------------------------------------------------
# _parse_skill_file: full SkillDefinition construction
# ---------------------------------------------------------------------------

def test_parse_skill_file_v2():
    sd = _parse_skill_file(V2_FULL, "research_assistant.md")
    assert isinstance(sd, SkillDefinition)
    assert sd.name == "Research Assistant"
    assert sd.category == "research"
    assert sd.version == "2.0"
    assert sd.chain_compatible is True
    assert sd.tools_used == ["web_search", "fetch_webpage"]
    assert len(sd.params) == 2
    assert isinstance(sd.params[0], SkillParam)
    assert sd.params[0].name == "depth"
    assert sd.params[0].required is False
    assert sd.params[0].default == "standard"
    assert sd.params[1].name == "format"
    assert sd.params[1].required is True
    assert sd.params[1].default is None


def test_parse_skill_file_v1_defaults():
    sd = _parse_skill_file(V1_SIMPLE, "morning_briefing.md")
    assert sd.category == "general"
    assert sd.params == []
    assert sd.tools_used == []
    assert sd.chain_compatible is True
    assert sd.version == "1.0"


def test_parse_skill_file_chain_compatible_false():
    text = """\
---
name: Solo
triggers: [solo]
description: Not chainable
chain_compatible: false
---
Do solo work."""
    sd = _parse_skill_file(text, "solo.md")
    assert sd.chain_compatible is False


def test_parse_skill_file_missing_name_uses_stem():
    text = """\
---
triggers: [hello]
description: A skill
---
Prompt."""
    sd = _parse_skill_file(text, "my_skill.md")
    assert sd.name == "my_skill"


def test_parse_skill_file_no_front_matter():
    """A file with no front-matter should still parse (using filename stem)."""
    text = "Just a plain prompt."
    # This will fail validation because triggers is empty — that's expected
    with pytest.raises(ValueError, match="triggers"):
        _parse_skill_file(text, "plain.md")


def test_parse_skill_file_params_required_default_coercion():
    """Ensure required='false' string is coerced to bool False."""
    text = """\
---
name: Parameterized
triggers: [test]
description: Has params
params:
  - name: level
    description: Detail level
    required: false
    default: medium
  - name: topic
    description: The topic
    required: true
---
Prompt with {level} and {topic}."""
    sd = _parse_skill_file(text, "parameterized.md")
    assert sd.params[0].required is False
    assert sd.params[0].default == "medium"
    assert sd.params[1].required is True
    assert sd.params[1].default is None
