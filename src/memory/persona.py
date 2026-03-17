"""
Persona Manager
---------------
Manages the agent's name, tone, and role from data/persona.json.
"""

import json
from pathlib import Path

_PERSONA_PATH = Path(__file__).parent.parent.parent / "data" / "persona.json"

_DEFAULTS = {
    "name": "Owlynn",
    "role": "AI study tutor and coding assistant",
    "tone": "friendly, encouraging, and clear",
    "language_preference": "match the user's preferred language"
}

VALID_FIELDS = {"name", "role", "tone", "language_preference"}


def get_persona() -> dict:
    """Load and return the current persona configuration."""
    try:
        with open(_PERSONA_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return {**_DEFAULTS, **data}
    except (FileNotFoundError, json.JSONDecodeError):
        _save_persona(_DEFAULTS)
        return _DEFAULTS.copy()


def update_persona_field(field: str, value: str) -> dict:
    """Update a single persona field and persist it."""
    if field not in VALID_FIELDS:
        raise ValueError(f"Unknown persona field '{field}'. Valid: {VALID_FIELDS}")
    persona = get_persona()
    persona[field] = value
    _save_persona(persona)
    return persona


def _save_persona(persona: dict):
    _PERSONA_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(_PERSONA_PATH, "w", encoding="utf-8") as f:
        json.dump(persona, f, ensure_ascii=False, indent=2)


def persona_to_system_prefix(persona: dict) -> str:
    """Format the persona as the opening of the system prompt."""
    return (
        f"You are {persona['name']}, a {persona['role']}.\n"
        f"Your tone is {persona['tone']}.\n"
        f"Language: {persona['language_preference']}.\n"
    )
