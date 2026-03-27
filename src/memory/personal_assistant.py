"""
Enhanced Memory Extraction & Management for Personal Assistant Behavior
========================================================================

This module provides intelligent memory extraction, topic identification,
and interest tracking to make Owlynn behave like a true personal assistant.

Features:
- Automatic conversation summarization
- Topic and interest extraction with TIME DECAY
- Dynamic "current focus" detection from recent activity
- Cross-conversation memory enrichment
- Semantic relationship tracking
- Natural memory decay (old interests fade, recent ones surface)
"""

import json
import math
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Optional, Tuple

# Memory storage location
MEMORIES_PATH = Path(__file__).parent.parent.parent / "data" / "memories.json"
TOPICS_PATH = Path(__file__).parent.parent.parent / "data" / "topics.json"
INTERESTS_PATH = Path(__file__).parent.parent.parent / "data" / "interests.json"
CONVERSATIONS_PATH = Path(__file__).parent.parent.parent / "data" / "conversations.json"

# --- Decay constants ---
# Half-life in days: after this many days, a topic/interest loses 50% relevance
TOPIC_HALF_LIFE_DAYS = 14
INTEREST_HALF_LIFE_DAYS = 21
# "Current focus" window: only activity within this window counts as active focus
FOCUS_WINDOW_DAYS = 3
# Minimum score to still be considered relevant (below this = effectively forgotten)
RELEVANCE_FLOOR = 0.05


def _time_decay(last_active_iso: str, half_life_days: float) -> float:
    """
    Exponential decay based on time since last activity.
    Returns a multiplier between 0.0 and 1.0.
    """
    try:
        last_active = datetime.fromisoformat(last_active_iso)
    except (ValueError, TypeError):
        return RELEVANCE_FLOOR
    age_days = max((datetime.now() - last_active).total_seconds() / 86400, 0)
    decay = 0.5 ** (age_days / half_life_days)
    return max(decay, RELEVANCE_FLOOR)



# ============================================================================
# TOPIC & INTEREST EXTRACTION
# ============================================================================

class TopicExtractor:
    """Extract topics and interests from conversations."""
    
    # Keywords for different topic categories
    TOPIC_PATTERNS = {
        "programming_languages": [
            r"\b(python|javascript|typescript|java|cpp|c\+\+|go|rust|ruby|php|swift|kotlin)\b",
            r"\b(js|ts|c#|csharp|perl|haskell|scala|elixir)\b"
        ],
        "frameworks": [
            r"\b(django|flask|fastapi|react|vue|angular|spring|spring-boot)\b",
            r"\b(next\.js|nuxt|express|rails|laravel|phoenix|actix)\b"
        ],
        "databases": [
            r"\b(postgres|postgresql|mysql|mongodb|redis|cassandra|dynamodb)\b",
            r"\b(elasticsearch|sqlite|mariadb|oracle|sql\s*server|cockroachdb)\b"
        ],
        "cloud_platforms": [
            r"\b(aws|azure|gcp|google\s*cloud|heroku|digitalocean)\b",
            r"\b(cloud|kubernetes|docker|container)\b"
        ],
        "devops_infra": [
            r"\b(kubernetes|k8s|docker|podman|terraform|ansible|jenkins|gitlab)\b",
            r"\b(ci\/cd|devops|infrastructure|deployment|container)\b"
        ],
        "ai_ml": [
            r"\b(llm|machine\s*learning|deep\s*learning|neural|transformers)\b",
            r"\b(tensorflow|pytorch|keras|huggingface|langchain|rag)\b"
        ],
        "frontend": [
            r"\b(html|css|responsive|ui|ux|design|accessibility|a11y)\b",
            r"\b(react|vue|angular|web\s*components)\b"
        ],
        "backend": [
            r"\b(backend|api|rest|graphql|microservices|scaling|performance)\b",
            r"\b(database|cache|async|concurrency)\b"
        ],
        "data": [
            r"\b(data|analytics|pipeline|etl|warehouse|lake)\b",
            r"\b(tableau|looker|tableau|jupyter)\b"
        ],
        "security": [
            r"\b(security|encryption|authentication|oauth|jwt|authorization)\b",
            r"\b(ssl|tls|https|penetration|vulnerability)\b"
        ],
    }
    
    INTEREST_PATTERNS = {
        "learning": r"\b(learning|studying|learning|course|tutorial|guide|documentation)\b",
        "debugging": r"\b(debug|troubleshoot|issue|error|bug|fix|problem|not working)\b",
        "optimization": r"\b(optimi(ze|z)|performance|speed|efficient|fast|slow)\b",
        "architecture": r"\b(architect|design|pattern|scalable|scale|modular)\b",
        "testing": r"\b(test|unit\s*test|integration|test-driven|tdd|pytest|jest)\b",
        "documentation": r"\b(document|readme|docstring|comment|explain)\b",
        "refactoring": r"\b(refactor|clean|improve|code\s*quality|simplify)\b",
        "deployment": r"\b(deploy|production|staging|release|ci\/cd|automation)\b",
    }

    @staticmethod
    def extract_topics(text: str) -> Dict[str, List[str]]:
        """Extract topics from text."""
        topics = {}
        text_lower = text.lower()
        
        for topic_category, patterns in TopicExtractor.TOPIC_PATTERNS.items():
            matches = set()
            for pattern in patterns:
                found = re.findall(pattern, text_lower, re.IGNORECASE)
                matches.update([m.lower() for m in found if m])
            if matches:
                topics[topic_category] = list(matches)
        
        return topics

    @staticmethod
    def extract_interests(text: str) -> Dict[str, bool]:
        """Detect user interests from conversational context."""
        interests = {}
        text_lower = text.lower()
        
        for interest, pattern in TopicExtractor.INTEREST_PATTERNS.items():
            interests[interest] = bool(re.search(pattern, text_lower))
        
        return {k: v for k, v in interests.items() if v}


# ============================================================================
# CONVERSATION SUMMARIZATION
# ============================================================================

class ConversationSummary:
    """Summarize conversations for memory storage."""
    
    @staticmethod
    def create_summary(messages: List[Dict], user_name: str = "User") -> Dict:
        """
        Create a structured summary of a conversation.
        
        Args:
            messages: List of {'role': 'user'|'assistant', 'content': str}
            user_name: User's name for personalization
        
        Returns:
            Dictionary with summary info
        """
        if not messages:
            return {}
        
        # Extract key info
        user_msgs = [m["content"] for m in messages if m.get("role") == "user"]
        ai_msgs = [m["content"] for m in messages if m.get("role") == "assistant"]
        
        # Find main topics discussed
        all_text = " ".join(user_msgs + ai_msgs)
        topics = TopicExtractor.extract_topics(all_text)
        interests = TopicExtractor.extract_interests(all_text)
        
        # Create summary
        summary = {
            "timestamp": datetime.now().isoformat(),
            "message_count": len(messages),
            "user_messages": len(user_msgs),
            "topics": topics,
            "interests": interests,
            "key_questions": user_msgs[:3],  # First 3 user messages as key questions
            "summary_text": ConversationSummary._generate_text_summary(user_msgs, ai_msgs)
        }
        
        return summary

    @staticmethod
    def _generate_text_summary(user_msgs: List[str], ai_msgs: List[str]) -> str:
        """Generate a text summary from conversation."""
        if not user_msgs:
            return ""
        
        # Combine first user message with key points
        first_q = user_msgs[0][:100] if user_msgs else ""
        
        summary = f"Discussed: {first_q}"
        if len(user_msgs) > 1:
            summary += f" (and {len(user_msgs)-1} follow-up questions)"
        
        return summary


# ============================================================================
# MEMORY ENRICHMENT & CONTEXT BUILDING
# ============================================================================

class MemoryEnricher:
    """Enrich and organize memories for better cross-conversation referencing."""
    
    @staticmethod
    def enrich_memory(fact: str, topics: Dict[str, List[str]], 
                      interests: Dict[str, bool]) -> Dict:
        """
        Enrich a fact with metadata for better retrieval.
        """
        return {
            "fact": fact,
            "created_at": datetime.now().isoformat(),
            "topics": topics,
            "interests": interests,
            "relevance_score": 1.0,
            "reference_count": 0,
            "related_facts": []
        }

    @staticmethod
    def calculate_relevance(memory: Dict) -> float:
        """
        Calculate memory relevance with natural time decay.
        Uses the same half-life decay as topics/interests for consistency.
        """
        created = memory.get("created_at", datetime.now().isoformat())
        base_decay = _time_decay(created, TOPIC_HALF_LIFE_DAYS)
        
        # Boost by reference count (being referenced keeps a memory alive)
        ref_boost = 1 + (memory.get("reference_count", 0) * 0.15)
        
        return base_decay * ref_boost


# ============================================================================
# TOPIC & INTEREST TRACKING (with natural time decay)
# ============================================================================

def load_topics() -> Dict[str, List[Dict]]:
    """Load tracked topics."""
    try:
        with open(TOPICS_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}

def save_topics(topics: Dict):
    """Save tracked topics."""
    TOPICS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(TOPICS_PATH, 'w', encoding='utf-8') as f:
        json.dump(topics, f, indent=2, ensure_ascii=False)

def track_topic(category: str, topic: str, strength: float = 1.0):
    """Track a topic of interest with time-aware strength."""
    topics = load_topics()
    
    if category not in topics:
        topics[category] = []
    
    existing = next((t for t in topics[category] if t["name"] == topic), None)
    
    if existing:
        existing["occurrences"] += 1
        existing["last_mentioned"] = datetime.now().isoformat()
        # Strength boost is smaller for repeated mentions (diminishing returns)
        existing["strength"] = min(existing["strength"] + 0.1, 5.0)
    else:
        topics[category].append({
            "name": topic,
            "occurrences": 1,
            "first_mentioned": datetime.now().isoformat(),
            "last_mentioned": datetime.now().isoformat(),
            "strength": strength
        })
    
    save_topics(topics)

def load_interests() -> Dict[str, Dict]:
    """Load user interests."""
    try:
        with open(INTERESTS_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}

def save_interests(interests: Dict):
    """Save user interests."""
    INTERESTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(INTERESTS_PATH, 'w', encoding='utf-8') as f:
        json.dump(interests, f, indent=2, ensure_ascii=False)

def update_interests(extracted_interests: Dict[str, bool]):
    """Update interests based on conversation analysis."""
    interests = load_interests()
    
    for interest, present in extracted_interests.items():
        if present:
            if interest not in interests:
                interests[interest] = {
                    "count": 1,
                    "first_observed": datetime.now().isoformat(),
                    "last_observed": datetime.now().isoformat(),
                    "strength": 1.0
                }
            else:
                interests[interest]["count"] += 1
                interests[interest]["last_observed"] = datetime.now().isoformat()
                interests[interest]["strength"] = min(interests[interest]["strength"] + 0.2, 5.0)
    
    save_interests(interests)


# ============================================================================
# CONVERSATION TRACKING
# ============================================================================

def load_conversations_history() -> List[Dict]:
    """Load conversation history."""
    try:
        with open(CONVERSATIONS_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return []

def save_conversations_history(history: List[Dict]):
    """Save conversation history."""
    CONVERSATIONS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(CONVERSATIONS_PATH, 'w', encoding='utf-8') as f:
        json.dump(history, f, indent=2, ensure_ascii=False)

def record_conversation(messages: List[Dict], session_id: str = None) -> Dict:
    """
    Record a conversation in history.
    
    Args:
        messages: List of message dicts
        session_id: Optional session identifier
    
    Returns:
        Recorded conversation summary
    """
    summary = ConversationSummary.create_summary(messages)
    summary["session_id"] = session_id or f"session_{datetime.now().timestamp()}"
    
    history = load_conversations_history()
    history.append(summary)
    
    # Keep last 100 conversations
    history = history[-100:]
    save_conversations_history(history)
    
    # Extract and track topics
    for category, items in summary.get("topics", {}).items():
        for item in items:
            track_topic(category, item)
    
    # Update interests
    update_interests(summary.get("interests", {}))
    
    return summary


# ============================================================================
# DYNAMIC MEMORY RETRIEVAL (with time decay & current focus)
# ============================================================================

def _score_topic(topic: dict) -> float:
    """
    Score a topic using time-decayed relevance.
    A topic mentioned 50 times a month ago scores LOWER than
    a topic mentioned 3 times today.
    """
    base_strength = topic.get("strength", 1.0)
    occurrences = topic.get("occurrences", 1)
    last_mentioned = topic.get("last_mentioned", topic.get("first_mentioned", ""))
    
    # Time decay is the dominant factor
    recency = _time_decay(last_mentioned, TOPIC_HALF_LIFE_DAYS)
    
    # Occurrence boost is logarithmic (diminishing returns)
    occurrence_factor = 1 + math.log1p(occurrences) * 0.3
    
    return base_strength * recency * occurrence_factor


def _score_interest(data: dict) -> float:
    """
    Score an interest using time-decayed relevance.
    Interests decay slower than topics (longer half-life) but still fade.
    """
    base_strength = data.get("strength", 1.0)
    count = data.get("count", 1)
    last_observed = data.get("last_observed", data.get("first_observed", ""))
    
    recency = _time_decay(last_observed, INTEREST_HALF_LIFE_DAYS)
    count_factor = 1 + math.log1p(count) * 0.2
    
    return base_strength * recency * count_factor


def get_current_focus(limit: int = 3) -> List[Tuple[str, str, float]]:
    """
    Detect what the user is CURRENTLY focused on.
    Only considers activity within the last FOCUS_WINDOW_DAYS.
    Returns: list of (category, topic_name, score) — the user's active focus areas.
    """
    topics = load_topics()
    cutoff = datetime.now() - timedelta(days=FOCUS_WINDOW_DAYS)
    focus_items = []
    
    for category, topic_list in topics.items():
        for topic in topic_list:
            last_mentioned = topic.get("last_mentioned", "")
            try:
                last_dt = datetime.fromisoformat(last_mentioned)
            except (ValueError, TypeError):
                continue
            
            if last_dt >= cutoff:
                # Within focus window — score by recency and frequency in window
                score = _score_topic(topic)
                focus_items.append((category, topic["name"], score))
    
    focus_items.sort(key=lambda x: x[2], reverse=True)
    return focus_items[:limit]


def get_relevant_topics(limit: int = 5) -> List[Tuple[str, str]]:
    """
    Get most relevant topics with time decay applied.
    Unlike get_current_focus, this looks at ALL topics but ranks by
    decayed relevance — old stuff naturally sinks.
    """
    topics = load_topics()
    all_topics = []
    
    for category, topic_list in topics.items():
        for topic in topic_list:
            score = _score_topic(topic)
            if score >= RELEVANCE_FLOOR:
                all_topics.append((category, topic["name"], score))
    
    all_topics.sort(key=lambda x: x[2], reverse=True)
    return [(cat, name) for cat, name, _ in all_topics[:limit]]


def get_fading_topics(limit: int = 3) -> List[Tuple[str, str, int]]:
    """
    Get topics that used to be active but are fading.
    Useful for the assistant to know "you used to work on X but haven't
    mentioned it in a while" — avoids assuming old interests are current.
    """
    topics = load_topics()
    fading = []
    cutoff_recent = datetime.now() - timedelta(days=FOCUS_WINDOW_DAYS)
    cutoff_old = datetime.now() - timedelta(days=60)
    
    for category, topic_list in topics.items():
        for topic in topic_list:
            last_mentioned = topic.get("last_mentioned", "")
            try:
                last_dt = datetime.fromisoformat(last_mentioned)
            except (ValueError, TypeError):
                continue
            
            # Not recent, but not ancient — the "fading" zone
            if cutoff_old <= last_dt < cutoff_recent and topic.get("occurrences", 0) >= 3:
                days_ago = (datetime.now() - last_dt).days
                fading.append((category, topic["name"], days_ago))
    
    fading.sort(key=lambda x: x[2])  # Most recently faded first
    return fading[:limit]


def get_user_interests_summary() -> str:
    """
    Get summary of user interests with time decay.
    Only surfaces interests that are still relevant.
    """
    interests = load_interests()
    
    scored = []
    for interest, data in interests.items():
        score = _score_interest(data)
        if score >= RELEVANCE_FLOOR:
            scored.append((interest, data, score))
    
    scored.sort(key=lambda x: x[2], reverse=True)
    
    summary_parts = []
    for interest, data, score in scored[:5]:
        label = interest.replace('_', ' ')
        # Add a qualitative indicator
        if score > 2.0:
            summary_parts.append(f"- {label} (very active)")
        elif score > 0.8:
            summary_parts.append(f"- {label} (active)")
        elif score > 0.3:
            summary_parts.append(f"- {label} (occasional)")
        else:
            summary_parts.append(f"- {label} (fading)")
    
    return "\n".join(summary_parts) if summary_parts else ""


def get_recent_conversation_summary(days: int = 7) -> str:
    """
    Get tiered summary of recent conversations.
    - Today: detailed
    - This week: condensed
    - Older: just topic mentions
    """
    history = load_conversations_history()
    now = datetime.now()
    today_cutoff = now - timedelta(days=1)
    week_cutoff = now - timedelta(days=days)
    
    today_summaries = []
    week_summaries = []
    
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
            # Today: include key questions for detail
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
    
    return "\n".join(parts) if parts else ""


# ============================================================================
# CONTEXT BUILDER (what gets injected into the system prompt)
# ============================================================================

def get_memory_context_for_prompt() -> str:
    """
    Build comprehensive, time-aware memory context for system prompt injection.
    
    Structure:
    1. Current Focus — what the user is actively working on RIGHT NOW
    2. Active Interests — what they care about (with decay labels)
    3. Recent Conversations — tiered by recency
    4. Fading Context — things they used to care about (so the assistant
       doesn't assume old interests are still current)
    """
    parts = []
    
    # 1. Current focus (last few days)
    focus = get_current_focus(3)
    if focus:
        parts.append("## Currently Focused On:")
        for category, topic, score in focus:
            parts.append(f"- {topic} ({category.replace('_', ' ')})")
    
    # 2. Broader relevant topics (time-decayed)
    topics = get_relevant_topics(5)
    # Filter out anything already in focus to avoid duplication
    focus_names = {t[1] for t in focus} if focus else set()
    filtered_topics = [(c, n) for c, n in topics if n not in focus_names]
    if filtered_topics:
        parts.append("\n## Also Interested In:")
        for category, topic in filtered_topics:
            parts.append(f"- {topic} ({category.replace('_', ' ')})")
    
    # 3. Active interests with decay labels
    interests = get_user_interests_summary()
    if interests:
        parts.append("\n## User Activity Patterns:")
        parts.append(interests)
    
    # 4. Recent conversations (tiered)
    recent = get_recent_conversation_summary(7)
    if recent:
        parts.append("\n## Recent Conversations:")
        parts.append(recent)
    
    # 5. Fading context (so the assistant knows what's no longer active)
    fading = get_fading_topics(3)
    if fading:
        parts.append("\n## Previously Active (not recently mentioned):")
        for category, topic, days_ago in fading:
            parts.append(f"- {topic} (last mentioned {days_ago} days ago)")
    
    return "\n".join(parts) if parts else ""
