"""
Cross-Session Memory Manager
-----------------------------
Persists important facts across chat sessions in data/memories.json.
The agent calls remember_fact() to store, recall_memories() to retrieve.
"""

import json
import re
from datetime import datetime
from pathlib import Path

_MEMORIES_PATH = Path(__file__).parent.parent.parent / "data" / "memories.json"
_MAX_MEMORIES = 200


def load_memories() -> list[dict]:
    """Load all memories from disk."""
    try:
        with open(_MEMORIES_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def save_memory(fact: str) -> str:
    """
    Save a new fact/memory to persistent storage.
    Returns a confirmation string.
    """
    memories = load_memories()
    
    # Avoid exact duplicates
    if any(m["fact"].lower().strip() == fact.lower().strip() for m in memories):
        return f"Memory already exists: '{fact}'"
    
    memories.append({
        "fact": fact.strip(),
        "timestamp": datetime.now().isoformat()
    })
    
    # Keep only the most recent N memories
    if len(memories) > _MAX_MEMORIES:
        memories = memories[-_MAX_MEMORIES:]
    
    _MEMORIES_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(_MEMORIES_PATH, "w", encoding="utf-8") as f:
        json.dump(memories, f, ensure_ascii=False, indent=2)
    
    return f"✅ Remembered: '{fact}'"


def search_memories(query: str, top_k: int = 8) -> list[dict]:
    """
    Search memories by keyword overlap with the query.
    Returns top_k most relevant memories (most recent first).
    """
    memories = load_memories()
    if not memories:
        return []
    
    query_words = set(re.findall(r"[a-z\u0e00-\u0e7f]+", query.lower()))
    
    scored = []
    for m in memories:
        fact_words = set(re.findall(r"[a-z\u0e00-\u0e7f]+", m["fact"].lower()))
        overlap = len(query_words & fact_words)
        scored.append((overlap, m))
    
    # Sort by overlap score (desc), then recency (desc)
    scored.sort(key=lambda x: (-x[0], x[1]["timestamp"]), reverse=False)
    
    # Always include at least the 3 most recent, regardless of relevance
    top = [m for _, m in scored if _ > 0][:top_k]
    recent = memories[-3:]
    seen = {m["fact"] for m in top}
    for m in recent:
        if m["fact"] not in seen:
            top.append(m)
    
    return top[:top_k]


def delete_memory(fact: str) -> bool:
    """
    Remove a specific fact from memories.
    Returns True if removed, False otherwise.
    """
    memories = load_memories()
    initial_count = len(memories)
    
    # Filter out the specific fact
    new_memories = [m for m in memories if m["fact"] != fact]
    
    if len(new_memories) < initial_count:
        with open(_MEMORIES_PATH, "w", encoding="utf-8") as f:
            json.dump(new_memories, f, ensure_ascii=False, indent=2)
        return True
    return False


def memories_to_context(query: str = "") -> str:
    """Format top memories as a system prompt context block."""
    memories = search_memories(query, top_k=8) if query else load_memories()[-8:]
    if not memories:
        return ""
    
    lines = ["LONG-TERM MEMORY (facts remembered from previous sessions):"]
    for m in memories:
        lines.append(f"  • {m['fact']}")
    lines.append("Use these facts to personalize your responses.")
    return "\n".join(lines)
