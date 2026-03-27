"""
Skills System — Reusable prompt templates loaded from skills/ folder.
Mirrors Cowork's Skills: domain-specific knowledge that triggers on keyword match.

Each skill is a markdown file in PROJECT_ROOT/skills/ with front-matter:
---
name: Morning Briefing
triggers: [briefing, morning, daily summary]
description: Creates a daily briefing from calendar/email/tasks
---
<prompt body>
"""

import re
from pathlib import Path
from typing import Optional
from langchain_core.tools import tool
from src.config.settings import PROJECT_ROOT

SKILLS_DIR = PROJECT_ROOT / "skills"


def _parse_front_matter(text: str) -> tuple[dict, str]:
    """Parse YAML-like front matter from a markdown skill file."""
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)", text, re.DOTALL)
    if not m:
        return {}, text
    meta_block, body = m.group(1), m.group(2)
    meta: dict = {}
    for line in meta_block.splitlines():
        line = line.strip()
        if ":" not in line:
            continue
        key, val = line.split(":", 1)
        key = key.strip()
        val = val.strip()
        if val.startswith("[") and val.endswith("]"):
            val = [v.strip().strip("'\"") for v in val[1:-1].split(",") if v.strip()]
        meta[key] = val
    return meta, body.strip()


def load_all_skills() -> list[dict]:
    """Load all skill definitions from the skills directory."""
    SKILLS_DIR.mkdir(parents=True, exist_ok=True)
    skills = []
    for f in sorted(SKILLS_DIR.glob("*.md")):
        try:
            text = f.read_text(encoding="utf-8")
            meta, body = _parse_front_matter(text)
            skills.append({
                "file": f.name,
                "name": meta.get("name", f.stem),
                "triggers": meta.get("triggers", []),
                "description": meta.get("description", ""),
                "prompt": body,
            })
        except Exception:
            continue
    return skills


def find_matching_skill(user_text: str) -> Optional[dict]:
    """Find a skill whose triggers match the user's message."""
    lower = user_text.lower()
    for skill in load_all_skills():
        triggers = skill.get("triggers", [])
        if isinstance(triggers, str):
            triggers = [triggers]
        for t in triggers:
            if t.lower() in lower:
                return skill
    return None


@tool
def list_skills() -> str:
    """
    Lists all available skills (reusable prompt templates).
    Skills are loaded from the skills/ directory.
    """
    skills = load_all_skills()
    if not skills:
        return "No skills found. Create .md files in the skills/ directory."
    lines = ["📚 Available Skills:"]
    for s in skills:
        triggers = ", ".join(s["triggers"]) if isinstance(s["triggers"], list) else str(s["triggers"])
        lines.append(f"  • {s['name']}: {s['description']}")
        lines.append(f"    Triggers: {triggers}")
    return "\n".join(lines)


@tool
def invoke_skill(skill_name: str, context: str = "") -> str:
    """
    Invokes a named skill and returns its prompt template with context filled in.
    Use this when the user's request matches a known skill pattern.

    Args:
        skill_name: Name of the skill to invoke.
        context: Additional context to inject into the skill prompt.
    """
    skills = load_all_skills()
    match = None
    name_lower = skill_name.lower()
    for s in skills:
        if s["name"].lower() == name_lower or s["file"].lower().startswith(name_lower):
            match = s
            break
    if not match:
        available = ", ".join(s["name"] for s in skills) or "none"
        return f"Skill '{skill_name}' not found. Available: {available}"

    prompt = match["prompt"]
    if context:
        prompt = prompt.replace("{context}", context).replace("{input}", context)
    return f"[Skill: {match['name']}]\n\n{prompt}"
