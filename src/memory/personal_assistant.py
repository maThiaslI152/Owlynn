"""
Enhanced Memory Extraction & Management for Personal Assistant Behavior
========================================================================

This module provides intelligent memory extraction, topic identification,
and interest tracking to make Owlynn behave like a true personal assistant.

Features:
- Automatic conversation summarization
- Topic and interest extraction
- Cross-conversation memory enrichment
- Semantic relationship tracking
- Memory decay (relevance scoring)
"""

import json
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Optional, Tuple

# Memory storage location
MEMORIES_PATH = Path(__file__).parent.parent.parent / "data" / "memories.json"
TOPICS_PATH = Path(__file__).parent.parent.parent / "data" / "topics.json"
INTERESTS_PATH = Path(__file__).parent.parent.parent / "data" / "interests.json"
CONVERSATIONS_PATH = Path(__file__).parent.parent.parent / "data" / "conversations.json"


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
        
        Args:
            fact: The base fact to enrich
            topics: Extracted topics
            interests: Extracted interests
        
        Returns:
            Enriched memory dict
        """
        return {
            "fact": fact,
            "created_at": datetime.now().isoformat(),
            "topics": topics,
            "interests": interests,
            "relevance_score": 1.0,  # Will decay over time
            "reference_count": 0,    # How many times referenced
            "related_facts": []      # IDs of related memories
        }

    @staticmethod
    def calculate_relevance(memory: Dict) -> float:
        """
        Calculate memory relevance score based on:
        - Age (newer = more relevant)
        - Reference frequency (referenced more = more relevant)
        - Decay function
        """
        created = datetime.fromisoformat(memory["created_at"])
        age_days = (datetime.now() - created).days
        
        # Exponential decay: 50% relevance at 30 days
        relevance = memory.get("relevance_score", 1.0) * (0.5 ** (age_days / 30))
        
        # Boost by reference count
        ref_boost = 1 + (memory.get("reference_count", 0) * 0.1)
        
        return relevance * ref_boost


# ============================================================================
# TOPIC & INTEREST TRACKING
# ============================================================================

def load_topics() -> Dict[str, List[Dict]]:
    """Load tracked topics."""
    try:
        with open(TOPICS_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)
    except:
        return {}

def save_topics(topics: Dict):
    """Save tracked topics."""
    TOPICS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(TOPICS_PATH, 'w', encoding='utf-8') as f:
        json.dump(topics, f, indent=2)

def track_topic(category: str, topic: str, strength: float = 1.0):
    """Track a topic of interest."""
    topics = load_topics()
    
    if category not in topics:
        topics[category] = []
    
    # Check if already tracked
    existing = next((t for t in topics[category] if t["name"] == topic), None)
    
    if existing:
        existing["occurrences"] += 1
        existing["last_mentioned"] = datetime.now().isoformat()
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
    except:
        return {}

def save_interests(interests: Dict):
    """Save user interests."""
    INTERESTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(INTERESTS_PATH, 'w', encoding='utf-8') as f:
        json.dump(interests, f, indent=2)

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
    except:
        return []

def save_conversations_history(history: List[Dict]):
    """Save conversation history."""
    CONVERSATIONS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(CONVERSATIONS_PATH, 'w', encoding='utf-8') as f:
        json.dump(history, f, indent=2)

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
# MEMORY RECOMMENDATION & RETRIEVAL
# ============================================================================

def get_relevant_topics(limit: int = 5) -> List[Tuple[str, str]]:
    """Get most relevant topics user is interested in."""
    topics = load_topics()
    all_topics = []
    
    for category, topic_list in topics.items():
        for topic in topic_list:
            relevance = (
                topic.get("strength", 1.0) * 
                (1 + topic.get("occurrences", 1) / 10)
            )
            all_topics.append((category, topic["name"], relevance))
    
    # Sort by relevance
    all_topics.sort(key=lambda x: x[2], reverse=True)
    
    return [(cat, name) for cat, name, _ in all_topics[:limit]]

def get_user_interests_summary() -> str:
    """Get summary of user interests for context."""
    interests = load_interests()
    
    summary_parts = []
    for interest, data in sorted(
        interests.items(), 
        key=lambda x: x[1].get("strength", 0), 
        reverse=True
    )[:5]:
        count = data.get("count", 1)
        summary_parts.append(f"- {interest.replace('_', ' ')}")
    
    return "\n".join(summary_parts) if summary_parts else ""

def get_recent_conversation_summary(days: int = 7) -> str:
    """Get summary of recent conversations."""
    history = load_conversations_history()
    cutoff = datetime.now() - timedelta(days=days)
    
    summaries = []
    for conv in history:
        try:
            conv_time = datetime.fromisoformat(conv.get("timestamp", ""))
            if conv_time > cutoff:
                summaries.append(conv.get("summary_text", ""))
        except:
            pass
    
    return "\n".join(summaries[:5]) if summaries else ""

def get_memory_context_for_prompt() -> str:
    """Build comprehensive memory context for system prompt injection."""
    parts = []
    
    # Recent topics
    topics = get_relevant_topics(5)
    if topics:
        parts.append("## Key Topics of Interest:")
        for category, topic in topics:
            parts.append(f"- {topic} ({category.replace('_', ' ')})")
    
    # Interests summary
    interests = get_user_interests_summary()
    if interests:
        parts.append("\n## User Interests:")
        parts.append(interests)
    
    # Recent conversations
    recent = get_recent_conversation_summary(7)
    if recent:
        parts.append("\n## Recent Conversation Topics:")
        parts.append(recent)
    
    return "\n".join(parts) if parts else ""
