# Personal Assistant Memory System

## Overview

Owlynn now includes a sophisticated personal assistant memory system that automatically:
- **Extracts topics** from conversations and categorizes them
- **Detects user interests** and tracks them over time
- **Records conversations** with automatic summarization
- **Enriches memory facts** with metadata for better context retrieval
- **Spans conversations** - remembers insights across multiple sessions

This system creates a true personal assistant experience where Owlynn learns about you and your work preferences, remembering key projects, interests, and topics across conversations.

## Architecture

### Core Components

#### 1. **Personal Assistant Module** (`src/memory/personal_assistant.py`)
The main module providing topic extraction, interest detection, conversation recording, and memory enrichment.

**Key Classes:**
- `TopicExtractor`: Pattern-based extraction of 10 topic categories
- `ConversationSummary`: Structured conversation representation
- `MemoryEnricher`: Adds metadata and relevance scores to facts

**Topic Categories:**
- Programming languages (Python, Go, Rust, JavaScript, etc.)
- Frameworks (React, FastAPI, Django, etc.)
- Databases (PostgreSQL, MongoDB, etc.)
- Cloud platforms (AWS, GCP, Azure)
- DevOps infrastructure (Docker, Kubernetes)
- AI/ML technologies
- Frontend technologies
- Backend technologies
- Data technologies
- Security concepts

**Interest Types:**
- Learning new concepts
- Debugging problems
- Optimization challenges
- Architecture design
- Testing strategies
- Documentation needs
- Refactoring opportunities
- Deployment concerns

#### 2. **Enhanced Memory Nodes** (`src/agent/nodes/memory.py`)
- `memory_inject_node()`: Injects enriched context from personal assistant before reasoning
- `memory_write_node()`: Records conversations and extracts topics/interests after response

#### 3. **Data Storage**
All personal assistant data is stored in JSON format for easy inspection and backup:
- `data/topics.json` - Tracked topics with occurrence counts and strength scores
- `data/interests.json` - Detected interests with occurrence counts
- `data/conversations.json` - Last 100 conversation summaries

## API Endpoints

### New Personal Assistant Endpoints

#### `GET /api/topics`
Returns tracked topics with relevance scores and recency.

**Response:**
```json
{
  "status": "ok",
  "topics": [
    {
      "topic": "FastAPI",
      "category": "frameworks",
      "count": 5,
      "strength": 0.95,
      "last_seen": "2024-01-15T10:30:00"
    }
  ]
}
```

#### `GET /api/interests`
Returns detected interests with occurrence counts.

**Response:**
```json
{
  "status": "ok",
  "interests": [
    {
      "interest": "optimization",
      "count": 3,
      "type": "optimization"
    },
    {
      "interest": "architecture",
      "count": 2,
      "type": "architecture"
    }
  ]
}
```

#### `GET /api/conversations`
Returns recent conversation history with summaries.

**Parameters:**
- `limit` (int, optional): Number of conversations to return (default: 10)

**Response:**
```json
{
  "status": "ok",
  "conversations": [
    {
      "user_message": "How do I optimize FastAPI startup?",
      "summary": "User asked about FastAPI optimization",
      "topics": ["FastAPI", "optimization"],
      "interests": ["optimization"],
      "timestamp": "2024-01-15T10:25:00"
    }
  ]
}
```

#### `GET /api/memory-context`
Returns comprehensive memory context for UI display.

**Response:**
```json
{
  "status": "ok",
  "memory_context": "User Interests: optimization, architecture\nRecent Topics: FastAPI, PostgreSQL\nProfile: ..."
}
```

#### `POST /api/topics/track`
Manually track a topic of interest.

**Request:**
```json
{
  "topic": "Kubernetes",
  "category": "devops_infra"
}
```

**Response:**
```json
{
  "status": "ok",
  "message": "Topic tracked",
  "topics": [...]
}
```

#### `POST /api/interests/update`
Manually update detected interests.

**Request:**
```json
{
  "interests": {
    "debugging": 2,
    "documentation": 1
  }
}
```

**Response:**
```json
{
  "status": "ok",
  "interests": [...]
}
```

## Frontend Integration

### Memory Tab UI Components

The Settings dialog's **Memory Tab** displays:

#### 1. **Tracked Topics** Section
- Displays top 10 topics as colored badges
- Shows occurrence count for each topic
- Color-coded by category (blue background)
- Format: `🏷️ TopicName [count]`

#### 2. **Detected Interests** Section
- Shows detected interest areas as green chips
- Includes occurrence count
- Format: `✨ InterestName [count]`

#### 3. **Recent Conversations** Section
- Lists last 5 conversations with summaries
- Shows conversation date
- Hoverable for quick reference
- Purple background for distinction

#### 4. **Memory Manager** Section (existing)
- Add new memory facts manually
- View stored memories
- Delete unwanted memories

### Frontend API Integration

**File:** `frontend/script.js`

Key functions:
- `loadSettingsData()` - Fetches all settings + topics + interests + conversations
- `loadMemoryTabData()` - Refreshes memory tab data when tab is opened
- `renderTrackedTopics()` - Renders topic badges
- `renderDetectedInterests()` - Renders interest chips
- `renderRecentConversations()` - Renders conversation cards

The Memory tab automatically refreshes when opened to show latest data.

## Data Flow

### Conversation Processing

1. **User sends message**
   ```
   Client → Server WebSocket
   ```

2. **Memory Injection** (in agent graph)
   ```
   memory_inject_node()
   → get_memory_context_for_prompt()
   → Enriched context included in system message
   ```

3. **Agent Response** (reasoning with context)
   ```
   LLM reasons with current + historical context
   ```

4. **Memory Write** (after response)
   ```
   memory_write_node()
   → record_conversation() - saves summary
   → extract topics/interests
   → create_enriched_fact() - saves with metadata
   → update_interests() - tracks interest types
   ```

5. **Data Available via API**
   ```
   Frontend calls /api/topics, /api/interests, /api/conversations
   Settings tab updates to show new data
   ```

## How Topics Are Extracted

### Pattern-Based Extraction

Topics are extracted using regex patterns organized by category:

**Example - Frameworks:**
```python
'fastapi': r'\b(fastapi|fast api)\b',
'django': r'\b(django)\b',
'react': r'\b(react\.js|react)\b',
```

**Example - AI/ML:**
```python
'langchain': r'\b(langchain|lang chain)\b',
'langraph': r'\b(langgraph|lang graph)\b',
```

When a user mentions "I'm building a FastAPI server", the TopicExtractor:
1. Searches for matching patterns in the message
2. Identifies "fastapi" from the frameworks category
3. Stores with occurrence count and timestamp

### Cross-Conversation Intelligence

The system maintains:
- **Occurrence counts** - How many times a topic appears
- **Strength scores** - Calculated from recency and frequency
- **Timestamps** - When each topic was last mentioned
- **Interest types** - What the user was doing (debugging, optimizing, learning, etc.)

This provides the agent with understanding like:
> "The user is deeply interested in FastAPI (5 mentions, strength 0.95) specifically around optimization (3 mentions). I should consider performance and scalability in my recommendations."

## Memory Enrichment

Facts are stored with metadata:

```json
{
  "fact": "User prefers async Python for high-performance services",
  "topics": ["Python", "async", "performance"],
  "interests": ["optimization"],
  "relevance_score": 0.92,
  "reference_count": 3,
  "related_facts": ["User works with FastAPI"],
  "timestamp": "2024-01-15T10:30:00"
}
```

Benefits:
- **Better retrieval**: Can find facts by topic or interest
- **Context awareness**: Agent knows why facts matter
- **Relevance ranking**: Recent, frequently referenced facts ranked higher
- **Related facts**: Can connect dots across memories

## Usage Examples

### Example 1: Cross-Conversation Reference

**Conversation 1:**
```
User: I'm optimizing a FastAPI application
Owlynn: [talks about FastAPI optimization]
[System records: Topic=FastAPI, Interest=optimization]
```

**Conversation 2 (later):**
```
User: How do I improve response times?
Owlynn: Based on your previous work with FastAPI, 
here are optimization strategies that worked before...
```

### Example 2: Interest-Based Suggestions

**After multiple conversations:**
- Topic tracking shows: FastAPI (5x), PostgreSQL (4x), Docker (3x)
- Interest tracking shows: optimization (5x), debugging (4x)

**New Conversation:**
```
User: I'm having issues with my deployment
Owlynn: Given your interest in debugging and experience with Docker,
let's check your containerization setup...
```

## Technical Details

### Storage Format

**topics.json:**
```json
{
  "frameworks": {
    "fastapi": {
      "count": 5,
      "strength": 0.95,
      "last_seen": "2024-01-15T10:30:00",
      "first_seen": "2024-01-10T14:00:00"
    }
  }
}
```

**interests.json:**
```json
{
  "optimization": {"count": 5, "type": "optimization"},
  "debugging": {"count": 4, "type": "debugging"}
}
```

**conversations.json:**
```json
[
  {
    "user_message": "...",
    "summary": "...",
    "topics": [...],
    "interests": [...],
    "timestamp": "2024-01-15T10:30:00"
  }
]
```

### Relevance Scoring

Topics get a strength score based on:
```
strength = (recency_score × 0.4) + (frequency_score × 0.6)

recency_score = 1.0 if mentioned today, decays exponentially
frequency_score = min(count / max_frequency, 1.0)
```

### Memory Decay

Topics that haven't been mentioned for 30+ days gradually decrease in strength, but are never deleted.

## Configuration

### Adding New Topics

Edit `src/memory/personal_assistant.py` `TOPIC_PATTERNS`:
```python
'new_topic': r'\b(new topic|alternate name)\b'
```

### Adding New Interest Types

Edit `INTEREST_PATTERNS`:
```python
'new_interest': r'pattern to detect interest'
```

### Changing Conversation History Limit

Edit in `personal_assistant.py`:
```python
MAX_CONVERSATIONS = 100  # Store last N conversations
```

## Limitations & Future Improvements

### Current Limitations
- Topics require exact pattern matches (could use NLP)
- Interests are keyword-based (could use semantic analysis)
- No topic merging (FastAPI vs fastapi stored separately without merging)
- Conversation summaries are user message only (could include response)

### Future Improvements
- NLP-based topic extraction using spaCy or NLTK
- Semantic similarity clustering of related topics
- Temporal topic trends (trending vs fading interests)
- Cross-project memory isolation
- Export/backup of learned knowledge
- Privacy controls for sensitive topics
- Memory sharing between similar topics

## Debugging

### View Tracked Topics
```bash
cat data/topics.json | python3 -m json.tool
```

### View Detected Interests
```bash
cat data/interests.json | python3 -m json.tool
```

### View Conversation History
```bash
cat data/conversations.json | python3 -m json.tool
```

### Clear Memory (caution!)
```bash
rm data/topics.json data/interests.json data/conversations.json
```

## API Testing

### Test topics endpoint
```bash
curl http://127.0.0.1:8000/api/topics | python3 -m json.tool
```

### Test interests endpoint
```bash
curl http://127.0.0.1:8000/api/interests | python3 -m json.tool
```

### Test conversations endpoint
```bash
curl http://127.0.0.1:8000/api/conversations?limit=5 | python3 -m json.tool
```

### Test memory context
```bash
curl http://127.0.0.1:8000/api/memory-context | python3 -m json.tool
```

## Summary

The Personal Assistant Memory System transforms Owlynn from a stateless conversation agent into a true personal assistant that:
- ✅ Learns your interests and preferences
- ✅ Remembers what you work on
- ✅ Provides context-aware assistance
- ✅ Spans multiple conversations intelligently
- ✅ Shows learned knowledge in Settings UI
- ✅ Maintains privacy with local storage
- ✅ Can be extended with new topic/interest types

This creates the foundation for increasingly personalized, context-aware assistance as you interact with Owlynn over time.
