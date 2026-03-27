"""Per-request project scope for workspace tools (matches WS/API project uploads)."""

from contextvars import ContextVar, Token

from src.config.settings import get_project_workspace, normalize_project_id

_active_project_id: ContextVar[str | None] = ContextVar("owlynn_active_project_id", default=None)


def tool_workspace_root() -> str:
    """Directory where chat uploads and project files for this turn live."""
    raw = _active_project_id.get()
    return get_project_workspace(raw)


def set_active_project_for_run(project_id: str | None) -> Token:
    token = _active_project_id.set(normalize_project_id(project_id))
    return token


def reset_active_project(token: Token) -> None:
    _active_project_id.reset(token)
