"""
Cross-Session Memory Manager (STM)
-----------------------------------
Persists important facts across chat sessions in data/memories.json.
The agent calls save_memory() to store, search_memories() to retrieve.
"""

import json
import logging
import re
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

_MEMORIES_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "memories.json"
_MAX_MEMORIES = 200
_SEARCH_WINDOW = 50


def _read_file() -> list[dict]:
    """Read memories from disk, returning [] on any error."""
    try:
        data = json.loads(_MEMORIES_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return []


def _write_file(memories: list[dict]) -> None:
    """Atomically write memories to disk via temp-file rename."""
    _MEMORIES_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = _MEMORIES_PATH.with_suffix(".tmp")
    try:
        tmp.write_text(
            json.dumps(memories, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        tmp.replace(_MEMORIES_PATH)
    except OSError as exc:
        logger.error("Failed to write memories: %s", exc)
        tmp.unlink(missing_ok=True)
        raise


def load_memories() -> list[dict]:
    """Load all memories from disk."""
    return _read_file()


def save_memory(fact: str) -> str:
    """Save a new fact/memory to persistent storage. Returns confirmation string."""
    fact = fact.strip()
    if not fact:
        return "Empty fact — nothing saved."

    memories = _read_file()

    # Avoid exact duplicates (case-insensitive)
    if any(m.get("fact", "").lower().strip() == fact.lower() for m in memories):
        return f"Memory already exists: '{fact}'"

    memories.append({"fact": fact, "timestamp": datetime.now().isoformat()})

    # Cap at max
    if len(memories) > _MAX_MEMORIES:
        memories = memories[-_MAX_MEMORIES:]

    _write_file(memories)
    return f"✅ Remembered: '{fact}'"


def search_memories(query: str, top_k: int = 8) -> list[dict]:
    """
    Keyword-overlap search over the most recent _SEARCH_WINDOW memories.
    Returns up to top_k matches sorted by relevance, falling back to
    the most recent memories when no keyword match is found.
    """
    memories = _read_file()
    if not memories:
        return []

    query_words = set(re.findall(r"[a-z\u0e00-\u0e7f]+", query.lower()))
    window = memories[-_SEARCH_WINDOW:] if len(memories) > _SEARCH_WINDOW else memories

    scored = []
    for m in window:
        fact_words = set(re.findall(r"[a-z\u0e00-\u0e7f]+", m.get("fact", "").lower()))
        overlap = len(query_words & fact_words)
        if overlap > 0:
            scored.append((overlap, m))

    if scored:
        scored.sort(key=lambda x: -x[0])
        return [m for _, m in scored[:top_k]]

    # Fallback: most recent
    return window[-top_k:]


def delete_memory(fact: str) -> bool:
    """Remove a specific fact from memories. Returns True if removed."""
    memories = _read_file()
    before = len(memories)
    filtered = [m for m in memories if m.get("fact") != fact]
    if len(filtered) < before:
        _write_file(filtered)
        return True
    return False


def clear_all_memories() -> int:
    """Delete every memory. Returns count removed."""
    count = len(_read_file())
    _write_file([])
    return count


def memories_to_context(query: str = "") -> str:
    """Format top memories as a system prompt context block."""
    memories = search_memories(query, top_k=8) if query else _read_file()[-8:]
    if not memories:
        return ""
    lines = ["LONG-TERM MEMORY (facts remembered from previous sessions):"]
    for m in memories:
        lines.append(f"  • {m.get('fact', '')}")
    lines.append("Use these facts to personalize your responses.")
    return "\n".join(lines)
