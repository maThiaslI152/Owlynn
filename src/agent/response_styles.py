"""User-selected response style → short system-prompt extension."""

from __future__ import annotations

STYLE_INSTRUCTIONS: dict[str, str] = {
    "normal": "",
    "learning": (
        "\n\nResponse style: Learning mode — teach clearly: define terms, use a concrete example "
        "where helpful, and build from simple to more detailed."
    ),
    "concise": (
        "\n\nResponse style: Concise — short paragraphs, no filler, bullet points when listing items."
    ),
    "explanatory": (
        "\n\nResponse style: Explanatory — structured answer with clear sections or bullets; "
        "assume the reader is new to the topic."
    ),
    "formal": (
        "\n\nResponse style: Formal and professional tone throughout."
    ),
}


def style_instruction_for_prompt(style: str | None) -> str:
    key = (style or "normal").strip().lower()
    return STYLE_INSTRUCTIONS.get(key, "")
