"""
Persona Manager
---------------
Manages the agent's name, tone, and role from data/persona.json.
"""

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_PERSONA_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "persona.json"

_DEFAULTS = {
    "name": "Owlynn",
    "role": "AI study tutor and coding assistant",
    "tone": "friendly, encouraging, and clear",
    "language_preference": "match the user's preferred language",
}

VALID_FIELDS = frozenset(_DEFAULTS.keys())


def get_persona() -> dict:
    """Load and return the current persona configuration."""
    try:
        data = json.loads(_PERSONA_PATH.read_text(encoding="utf-8"))
        return {**_DEFAULTS, **data}
    except (FileNotFoundError, json.JSONDecodeError, OSError) as exc:
        logger.debug("Persona file missing or corrupt, writing defaults: %s", exc)
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


def reset_persona() -> dict:
    """Reset persona to defaults and persist."""
    _save_persona(_DEFAULTS)
    return _DEFAULTS.copy()


def _save_persona(persona: dict) -> None:
    """Atomically write persona to disk via temp-file rename."""
    _PERSONA_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = _PERSONA_PATH.with_suffix(".tmp")
    try:
        tmp.write_text(
            json.dumps(persona, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        tmp.replace(_PERSONA_PATH)
    except OSError as exc:
        logger.error("Failed to write persona: %s", exc)
        tmp.unlink(missing_ok=True)
        raise


def persona_to_system_prefix(persona: dict) -> str:
    """Format the persona as the opening of the system prompt."""
    return (
        f"You are {persona['name']}, a {persona['role']}.\n"
        f"Your tone is {persona['tone']}.\n"
        f"Language: {persona['language_preference']}.\n"
    )
