"""
AskUserQuestion Tool — Let the agent ask clarifying questions mid-task.
Mirrors Cowork's AskUserQuestion for HITL interaction during complex workflows.

Uses LangGraph's interrupt() to pause execution and wait for user input.
"""

from langchain_core.tools import tool
from langgraph.types import interrupt


@tool
def ask_user(question: str) -> str:
    """
    Asks the user a clarifying question and waits for their response.
    Use this when you need more information to complete a task accurately.

    The task will pause until the user responds.

    Args:
        question: The question to ask the user.
    """
    # interrupt() pauses the graph and sends the question to the frontend.
    # When the user responds via Command(resume=...), execution continues
    # with the response as the return value.
    response = interrupt({"type": "ask_user", "question": question})
    if isinstance(response, dict):
        return response.get("answer", str(response))
    return str(response)
