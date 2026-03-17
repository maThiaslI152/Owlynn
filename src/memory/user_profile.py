"""
User Profile Manager
--------------------
Stores and retrieves user preferences from data/user_profile.json.
"""

import json
from pathlib import Path

_PROFILE_PATH = Path(__file__).parent.parent.parent / "data" / "user_profile.json"

_DEFAULTS = {
    "name": "User",
    "preferred_language": "en",
    "education_level": "university",
    "domains_of_interest": [],
    "response_style": "detailed",
    "llm_base_url": "http://127.0.0.1:8080/v1",
    "llm_model_name": "mlx-community/Qwen2-VL-7B-Instruct-4bit"
}

VALID_FIELDS = {
    "name": str,
    "preferred_language": str,   # "en", "th", etc.
    "education_level": str,      # "high_school", "university", "professional"
    "domains_of_interest": list,
    "response_style": str,       # "concise", "detailed", "step_by_step"
    "llm_base_url": str,
    "llm_model_name": str
}


def get_profile() -> dict:
    """Load and return the current user profile."""
    try:
        with open(_PROFILE_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        # Merge with defaults for any missing keys
        return {**_DEFAULTS, **data}
    except (FileNotFoundError, json.JSONDecodeError):
        _save_profile(_DEFAULTS)
        return _DEFAULTS.copy()


def update_profile(field: str, value) -> dict:
    """Update a single field in the user profile and return the updated profile."""
    if field not in VALID_FIELDS:
        raise ValueError(f"Unknown profile field '{field}'. Valid fields: {list(VALID_FIELDS.keys())}")
    
    profile = get_profile()
    
    # Coerce value type
    expected_type = VALID_FIELDS[field]
    if expected_type == list and isinstance(value, str):
        value = [v.strip() for v in value.split(",")]
    
    profile[field] = value
    _save_profile(profile)
    return profile


def _save_profile(profile: dict):
    _PROFILE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(_PROFILE_PATH, "w", encoding="utf-8") as f:
        json.dump(profile, f, ensure_ascii=False, indent=2)


def profile_to_context(profile: dict) -> str:
    """Format the profile as a system prompt context block."""
    lang_map = {"en": "English", "th": "Thai", "ja": "Japanese", "zh": "Chinese"}
    lang = lang_map.get(profile.get("preferred_language", "en"), profile.get("preferred_language", "English"))
    domains = ", ".join(profile.get("domains_of_interest", [])) or "general topics"
    
    return (
        f"USER PROFILE:\n"
        f"- Name: {profile.get('name', 'User')}\n"
        f"- Preferred response language: {lang}\n"
        f"- Education level: {profile.get('education_level', 'university')}\n"
        f"- Domains of interest: {domains}\n"
        f"- Response style: {profile.get('response_style', 'detailed')}\n"
        f"Always address the user by their name and adapt your language and depth accordingly."
    )
