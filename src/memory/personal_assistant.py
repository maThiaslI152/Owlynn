"""
Enhanced Memory Extraction & Management for Personal Assistant Behavior
========================================================================

Provides intelligent memory extraction, topic identification,
and interest tracking with natural time decay.

Features:
- Automatic conversation summarization
- Topic and interest extraction with TIME DECAY
- Dynamic "current focus" detection from recent activity
- Cross-conversation memory enrichment
"""

import json
import logging
import math
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

_DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
MEMORIES_PATH = _DATA_DIR / "memories.json"
TOPICS_PATH = _DATA_DIR / "topics.json"
INTERESTS_PATH = _DATA_DIR / "interests.json"
CONVERSATIONS_PATH = _DATA_DIR / "conversations.json"

# Decay constants
TOPIC_HALF_LIFE_DAYS = 14
INTEREST_HALF_LIFE_DAYS = 21
FOCUS_WINDOW_DAYS = 3
RELEVANCE_FLOOR = 0.05


# ── Helpers ──────────────────────────────────────────────────────────────────

def _time_decay(last_active_iso: str, half_life_days: float) -> float:
    """Exponential decay based on time since last activity. Returns 0.0–1.0."""
    try:
        last_active = datetime.fromisoformat(last_active_iso)
    except (ValueError, TypeError):
        return RELEVANCE_FLOOR
    age_days = max((datetime.now() - last_active).total_seconds() / 86400, 0)
    return max(0.5 ** (age_days / half_life_days), RELEVANCE_FLOOR)


def _read_json(path: Path, default=None):
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return default if default is not None else {}


def _write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    try:
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        tmp.replace(path)
    except OSError as exc:
        logger.error("Failed to write %s: %s", path, exc)
        tmp.unlink(missing_ok=True)
        raise


# ── Topic & Interest Extraction ─────────────────────────────────────────────

class TopicExtractor:
    """Extract topics and interests from conversations."""

    TOPIC_PATTERNS = {
        "programming_languages": [
            r"\b(python|javascript|typescript|java|cpp|c\+\+|go|rust|ruby|php|swift|kotlin)\b",
            r"\b(js|ts|c#|csharp|perl|haskell|scala|elixir)\b",
        ],
        "frameworks": [
            r"\b(django|flask|fastapi|react|vue|angular|spring|spring-boot)\b",
            r"\b(next\.js|nuxt|express|rails|laravel|phoenix|actix)\b",
        ],
        "databases": [
            r"\b(postgres|postgresql|mysql|mongodb|redis|cassandra|dynamodb)\b",
            r"\b(elasticsearch|sqlite|mariadb|oracle|sql\s*server|cockroachdb)\b",
        ],
        "cloud_platforms": [
            r"\b(aws|azure|gcp|google\s*cloud|heroku|digitalocean)\b",
            r"\b(cloud|kubernetes|docker|container)\b",
        ],
        "devops_infra": [
            r"\b(kubernetes|k8s|docker|podman|terraform|ansible|jenkins|gitlab)\b",
            r"\b(ci\/cd|devops|infrastructure|deployment|container)\b",
        ],
        "ai_ml": [
            r"\b(llm|machine\s*learning|deep\s*learning|neural|transformers)\b",
            r"\b(tensorflow|pytorch|keras|huggingface|langchain|rag)\b",
        ],
        "frontend": [
            r"\b(html|css|responsive|ui|ux|design|accessibility|a11y)\b",
            r"\b(react|vue|angular|web\s*components)\b",
        ],
        "backend": [
            r"\b(backend|api|rest|graphql|microservices|scaling|performance)\b",
            r"\b(database|cache|async|concurrency)\b",
        ],
        "data": [
            r"\b(data|analytics|pipeline|etl|warehouse|lake)\b",
            r"\b(tableau|looker|jupyter)\b",
        ],
        "security": [
            r"\b(security|encryption|authentication|oauth|jwt|authorization)\b",
            r"\b(ssl|tls|https|penetration|vulnerability)\b",
        ],
    }

    INTEREST_PATTERNS = {
        "learning": r"\b(learning|studying|course|tutorial|guide|documentation)\b",
        "debugging": r"\b(debug|troubleshoot|issue|error|bug|fix|problem|not working)\b",
        "optimization": r"\b(optimi[zs]e|performance|speed|efficient|fast|slow)\b",
        "architecture": r"\b(architect|design|pattern|scalable|scale|modular)\b",
        "testing": r"\b(test|unit\s*test|integration|test-driven|tdd|pytest|jest)\b",
        "documentation": r"\b(document|readme|docstring|comment|explain)\b",
        "refactoring": r"\b(refactor|clean|improve|code\s*quality|simplify)\b",
        "deployment": r"\b(deploy|production|staging|release|ci\/cd|automation)\b",
    }

    @staticmethod
    def extract_topics(text: str) -> Dict[str, List[str]]:
        topics: Dict[str, List[str]] = {}
        text_lower = text.lower()
        for category, patterns in TopicExtractor.TOPIC_PATTERNS.items():
            matches: set[str] = set()
            for pattern in patterns:
                found = re.findall(pattern, text_lower, re.IGNORECASE)
                matches.update(m.lower() for m in found if m)
            if matches:
                topics[category] = sorted(matches)
        return topics

    @staticmethod
    def extract_interests(text: str) -> Dict[str, bool]:
        text_lower = text.lower()
        return {
            interest: True
            for interest, pattern in TopicExtractor.INTEREST_PATTERNS.items()
            if re.search(pattern, text_lower)
        }


# ── Conversation Summarization ───────────────────────────────────────────────

class ConversationSummary:
    @staticmethod
    def create_summary(messages: List[Dict], user_name: str = "User") -> Dict:
        if not messages:
            return {}
        user_msgs = [m["content"] for m in messages if m.get("role") == "user"]
        ai_msgs = [m["content"] for m in messages if m.get("role") == "assistant"]
        all_text = " ".join(user_msgs + ai_msgs)
        topics = TopicExtractor.extract_topics(all_text)
        interests = TopicExtractor.extract_interests(all_text)
        return {
            "timestamp": datetime.now().isoformat(),
            "message_count": len(messages),
            "user_messages": len(user_msgs),
            "topics": topics,
            "interests": interests,
            "key_questions": user_msgs[:3],
            "summary_text": ConversationSummary._generate_text_summary(user_msgs, ai_msgs),
        }

    @staticmethod
    def _generate_text_summary(user_msgs: List[str], ai_msgs: List[str]) -> str:
        if not user_msgs:
            return ""
        first_q = user_msgs[0][:100]
        summary = f"Discussed: {first_q}"
        if len(user_msgs) > 1:
            summary += f" (and {len(user_msgs) - 1} follow-up questions)"
        return summary


# ── Memory Enrichment ────────────────────────────────────────────────────────

class MemoryEnricher:
    @staticmethod
    def enrich_memory(fact: str, topics: Dict[str, List[str]], interests: Dict[str, bool]) -> Dict:
        return {
            "fact": fact,
            "created_at": datetime.now().isoformat(),
            "topics": topics,
            "interests": interests,
            "relevance_score": 1.0,
            "reference_count": 0,
            "related_facts": [],
        }

    @staticmethod
    def calculate_relevance(memory: Dict) -> float:
        created = memory.get("created_at", datetime.now().isoformat())
        base_decay = _time_decay(created, TOPIC_HALF_LIFE_DAYS)
        ref_boost = 1 + (memory.get("reference_count", 0) * 0.15)
        return base_decay * ref_boost


# ── Topic & Interest Tracking ────────────────────────────────────────────────

def load_topics() -> Dict[str, List[Dict]]:
    return _read_json(TOPICS_PATH, {})


def save_topics(topics: Dict) -> None:
    _write_json(TOPICS_PATH, topics)


def track_topic(category: str, topic: str, strength: float = 1.0) -> None:
    topics = load_topics()
    if category not in topics:
        topics[category] = []

    existing = next((t for t in topics[category] if t["name"] == topic), None)
    now = datetime.now().isoformat()

    if existing:
        existing["occurrences"] += 1
        existing["last_mentioned"] = now
        existing["strength"] = min(existing["strength"] + 0.1, 5.0)
    else:
        topics[category].append({
            "name": topic,
            "occurrences": 1,
            "first_mentioned": now,
            "last_mentioned": now,
            "strength": strength,
        })
    save_topics(topics)


def load_interests() -> Dict[str, Dict]:
    return _read_json(INTERESTS_PATH, {})


def save_interests(interests: Dict) -> None:
    _write_json(INTERESTS_PATH, interests)


def update_interests(extracted_interests: Dict[str, bool]) -> None:
    interests = load_interests()
    now = datetime.now().isoformat()
    for interest, present in extracted_interests.items():
        if not present:
            continue
        if interest not in interests:
            interests[interest] = {
                "count": 1,
                "first_observed": now,
                "last_observed": now,
                "strength": 1.0,
            }
        else:
            interests[interest]["count"] += 1
            interests[interest]["last_observed"] = now
            interests[interest]["strength"] = min(interests[interest]["strength"] + 0.2, 5.0)
    save_interests(interests)


# ── Conversation Tracking ────────────────────────────────────────────────────

def load_conversations_history(limit: Optional[int] = None) -> List[Dict]:
    data = _read_json(CONVERSATIONS_PATH, [])
    if not isinstance(data, list):
        return []
    if limit and limit > 0:
        return data[-limit:]
    return data


def save_conversations_history(history: List[Dict]) -> None:
    _write_json(CONVERSATIONS_PATH, history)


def record_conversation(messages: List[Dict], session_id: str = None) -> Dict:
    summary = ConversationSummary.create_summary(messages)
    summary["session_id"] = session_id or f"session_{datetime.now().timestamp()}"

    history = load_conversations_history()
    history.append(summary)
    history = history[-100:]  # keep last 100
    save_conversations_history(history)

    for category, items in summary.get("topics", {}).items():
        for item in items:
            track_topic(category, item)
    update_interests(summary.get("interests", {}))
    return summary


# ── Dynamic Memory Retrieval (with time decay) ──────────────────────────────

def _score_topic(topic: dict) -> float:
    base_strength = topic.get("strength", 1.0)
    occurrences = topic.get("occurrences", 1)
    last_mentioned = topic.get("last_mentioned", topic.get("first_mentioned", ""))
    recency = _time_decay(last_mentioned, TOPIC_HALF_LIFE_DAYS)
    occurrence_factor = 1 + math.log1p(occurrences) * 0.3
    return base_strength * recency * occurrence_factor


def _score_interest(data: dict) -> float:
    base_strength = data.get("strength", 1.0)
    count = data.get("count", 1)
    last_observed = data.get("last_observed", data.get("first_observed", ""))
    recency = _time_decay(last_observed, INTEREST_HALF_LIFE_DAYS)
    count_factor = 1 + math.log1p(count) * 0.2
    return base_strength * recency * count_factor


def get_current_focus(limit: int = 3) -> List[Tuple[str, str, float]]:
    """Detect what the user is CURRENTLY focused on (last FOCUS_WINDOW_DAYS)."""
    topics = load_topics()
    cutoff = datetime.now() - timedelta(days=FOCUS_WINDOW_DAYS)
    focus_items = []
    for category, topic_list in topics.items():
        for topic in topic_list:
            try:
                last_dt = datetime.fromisoformat(topic.get("last_mentioned", ""))
            except (ValueError, TypeError):
                continue
            if last_dt >= cutoff:
                focus_items.append((category, topic["name"], _score_topic(topic)))
    focus_items.sort(key=lambda x: -x[2])
    return focus_items[:limit]


def get_relevant_topics(limit: int = 5) -> List[Tuple[str, str]]:
    """Get most relevant topics with time decay applied."""
    topics = load_topics()
    all_topics = []
    for category, topic_list in topics.items():
        for topic in topic_list:
            score = _score_topic(topic)
            if score >= RELEVANCE_FLOOR:
                all_topics.append((category, topic["name"], score))
    all_topics.sort(key=lambda x: -x[2])
    return [(cat, name) for cat, name, _ in all_topics[:limit]]


def get_fading_topics(limit: int = 3) -> List[Tuple[str, str, int]]:
    """Get topics that used to be active but are fading."""
    topics = load_topics()
    cutoff_recent = datetime.now() - timedelta(days=FOCUS_WINDOW_DAYS)
    cutoff_old = datetime.now() - timedelta(days=60)
    fading = []
    for category, topic_list in topics.items():
        for topic in topic_list:
            try:
                last_dt = datetime.fromisoformat(topic.get("last_mentioned", ""))
            except (ValueError, TypeError):
                continue
            if cutoff_old <= last_dt < cutoff_recent and topic.get("occurrences", 0) >= 3:
                fading.append((category, topic["name"], (datetime.now() - last_dt).days))
    fading.sort(key=lambda x: x[2])
    return fading[:limit]


def get_user_interests_summary() -> str:
    """Get summary of user interests with time decay."""
    interests = load_interests()
    scored = []
    for interest, data in interests.items():
        score = _score_interest(data)
        if score >= RELEVANCE_FLOOR:
            scored.append((interest, data, score))
    scored.sort(key=lambda x: -x[2])

    parts = []
    for interest, _data, score in scored[:5]:
        label = interest.replace("_", " ")
        if score > 2.0:
            parts.append(f"- {label} (very active)")
        elif score > 0.8:
            parts.append(f"- {label} (active)")
        elif score > 0.3:
            parts.append(f"- {label} (occasional)")
        else:
            parts.append(f"- {label} (fading)")
    return "\n".join(parts)


def get_recent_conversation_summary(days: int = 7) -> str:
    """Get tiered summary of recent conversations."""
    history = load_conversations_history()
    now = datetime.now()
    today_cutoff = now - timedelta(days=1)
    week_cutoff = now - timedelta(days=days)

    today_summaries: list[str] = []
    week_summaries: list[str] = []

    for conv in reversed(history):
        try:
            conv_time = datetime.fromisoformat(conv.get("timestamp", ""))
        except (ValueError, TypeError):
            continue
        if conv_time < week_cutoff:
            break
        summary_text = conv.get("summary_text", "")
        if not summary_text:
            continue
        if conv_time >= today_cutoff:
            questions = conv.get("key_questions", [])
            detail = summary_text
            if questions:
                detail += f" — asked about: {questions[0][:80]}"
            today_summaries.append(detail)
        else:
            week_summaries.append(summary_text)

    parts = []
    if today_summaries:
        parts.append("Today:")
        parts.extend(f"  - {s}" for s in today_summaries[:3])
    if week_summaries:
        parts.append("Earlier this week:")
        parts.extend(f"  - {s}" for s in week_summaries[:3])
    return "\n".join(parts)


# ── Context Builder ──────────────────────────────────────────────────────────

def get_memory_context_for_prompt() -> str:
    """Build comprehensive, time-aware memory context for system prompt injection."""
    parts = []

    focus = get_current_focus(3)
    if focus:
        parts.append("## Currently Focused On:")
        for category, topic, _score in focus:
            parts.append(f"- {topic} ({category.replace('_', ' ')})")

    topics = get_relevant_topics(5)
    focus_names = {t[1] for t in focus} if focus else set()
    filtered = [(c, n) for c, n in topics if n not in focus_names]
    if filtered:
        parts.append("\n## Also Interested In:")
        for category, topic in filtered:
            parts.append(f"- {topic} ({category.replace('_', ' ')})")

    interests = get_user_interests_summary()
    if interests:
        parts.append("\n## User Activity Patterns:")
        parts.append(interests)

    recent = get_recent_conversation_summary(7)
    if recent:
        parts.append("\n## Recent Conversations:")
        parts.append(recent)

    fading = get_fading_topics(3)
    if fading:
        parts.append("\n## Previously Active (not recently mentioned):")
        for _category, topic, days_ago in fading:
            parts.append(f"- {topic} (last mentioned {days_ago} days ago)")

    return "\n".join(parts)
