# Agent Flow (LangGraph)

## Graph Topology

```
START → memory_inject → router → simple → memory_write → END
                               → complex_llm ←──────────────┐
                                    ↓                        │
                               security_proxy                │
                                    ↓                        │
                               tool_action ──────────────────┘
                                    ↓
                               memory_write → END
```

## Node Details

### memory_inject
- Builds `memory_context` from Mem0 search + user profile + topics/interests
- Filters out config fields (LLM URLs, tokens, etc.) from profile
- Caches context per thread (5-min TTL)

### router
- Keyword bypass for greetings → `simple`
- Web intent detection → `complex`
- Conversation with tool history → stays `complex`
- Falls back to LFM2.5-1.2B JSON classification
- Default fallback: `complex`

### simple
- LFM2.5-1.2B, no tools, no memory context in prompt
- Strips `<think>` tags and reasoning artifacts
- Falls back to Qwen3.5-9B on model failure
- Injects current date and response style

### complex_llm
- Qwen3.5-9B with 20 tools bound
- Injects current date, memory context, persona, response style
- Strips `<think>` tags from output
- Auto-reads workspace files when model outputs prose instead of tool calls
- Sets `pending_tool_calls` flag for security proxy

### security_proxy
- Checks tool names against `SENSITIVE_TOOLS` set
- Checks arguments for dangerous patterns (rm -rf, sudo, etc.)
- Safe tools: auto-approved
- Sensitive tools: HITL interrupt (approval modal in frontend)
- Denied: flow exits to memory_write

### tool_action
- Executes approved tool calls via LangGraph ToolNode
- Appends fetch retry nudges for failed static fetches
- Appends web search answer nudges for successful searches
- Returns to complex_llm for next reasoning step

### memory_write
- Records conversation via personal_assistant module
- Extracts topics and interests
- Saves enriched facts to Mem0/ChromaDB
- Invalidates memory context cache

## Tool Binding

Defined in `src/agent/tool_sets.py`:
- `COMPLEX_TOOLS_WITH_WEB` (20 tools)
- `COMPLEX_TOOLS_NO_WEB` (18 tools, no web_search/fetch_webpage)
