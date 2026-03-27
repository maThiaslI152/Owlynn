"""
AskUserQuestion Tool — Let the agent ask clarifying questions mid-task.

Supports 1-3 suggested choices plus a free-text option.
Uses LangGraph interrupt() to pause and wait for user input.
"""

from langchain_core.tools import tool
from langgraph.types import interrupt


@tool
def ask_user(question: str, choices: str = "") -> str:
    """
    Asks the user a clarifying question and waits for their response.
    Use this ONCE when a request is clearly ambiguous. Don't over-ask.

    The user sees the question with clickable choice buttons (if provided)
    plus a free-text input for custom answers.

    Args:
        question: The question to ask.
        choices: Optional comma-separated choices (1-3 max). Example: "PDF,Word,PowerPoint"
    """
    choice_list = [c.strip() for c in choices.split(",") if c.strip()][:3] if choices else []
    response = interrupt({
        "type": "ask_user",
        "question": question,
        "choices": choice_list,
    })
    if isinstance(response, dict):
        return response.get("answer", str(response))
    return str(response)
