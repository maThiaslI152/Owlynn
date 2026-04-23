"""
State Definition for the Local Cowork Agent.

This module defines the `AgentState` TypedDict used by LangGraph to maintain
conversation history, execution mode, and other contextual flags.
"""

import operator
from typing import Annotated, TypedDict, Sequence
from langchain_core.messages import BaseMessage

from langgraph.graph.message import add_messages


class AgentState(TypedDict):
    """
    Represents the internal state of the Local Cowork Agent during execution.
    It relies entirely on standard Python dicts to be easily serializable by Langgraph checks.
    """
    
    # The active conversation/reasoning history
    # Using `add_messages` allows handling `RemoveMessage` to delete older items.
    messages: Annotated[Sequence[BaseMessage], add_messages]
    
    # Internal scratchpad/status that doesn't need to be kept forever in messages
    current_task: str | None
    
    # Any structured facts discovered in this specific thread (to be sent to Mem0 eventually)
    extracted_facts: Annotated[list[str], operator.add]
    
    # Arbitrary context retrieved from VectorDB/Mem0 before reasoning
    long_term_context: str | None
    
    # Execution mode: 'tools_off' or 'tools_on'
    mode: str | None

    # When False, complex path binds tools without web_search (UI "Web search" off).
    web_search_enabled: bool | None

    # Chat response style: normal | learning | concise | explanatory | formal
    response_style: str | None

    # Project ID to associate this conversation with a specific project
    project_id: str | None

    # Track if any tool execution was vetted/approved by security node
    execution_approved: bool | None

    # Routing decision: 'simple', 'complex-default', 'complex-vision', 'complex-longctx', or 'complex-cloud'
    route: str | None
    # Model provenance: 'small-local', 'medium-default', 'medium-vision', 'medium-longctx',
    # 'large-cloud', or any of these with '-fallback' suffix
    model_used: str | None
    memory_context: str | None     # Formatted context string
    persona: str | None            # Persona summary string

    # Which M-tier variant is currently loaded ("default", "vision", "longctx", or None)
    current_medium_model: str | None

    # Toolbox names selected by the router (e.g. ["web_search", "file_ops"] or ["all"])
    selected_toolboxes: list[str] | None

    # Dynamic token budget — set by the router based on request complexity
    token_budget: int | None

    # Secure cyclic tool flow state
    pending_tool_calls: bool | None
    pending_tool_names: Annotated[list[str], operator.add]
    security_decision: str | None  # 'approved' | 'denied'
    security_reason: str | None

    # Cloud cost tracking — token usage from DeepSeek API
    api_tokens_used: dict | None  # {"prompt_tokens": int, "completion_tokens": int}

    # Whether the router asked for user clarification this turn
    router_clarification_used: bool | None

    # Router metadata for telemetry — populated by router_node on each routing decision
    router_metadata: dict | None

    # Fallback chain for telemetry — ordered list of model attempts in complex_llm_node
    fallback_chain: list[dict] | None

    # ── Auto-summarize state ───────────────────────────────────────────
    # Current active token count (used for summarization threshold check)
    active_tokens: int | None
    # Context window size of the active model
    context_window: int | None
    # Cumulative tokens summarized in this thread (for observability)
    summarized_tokens: int | None
    # Takeaway strings from the most recent summarization
    summary_takeaways: list[str] | None
    # Payload for the context_summarized WS event
    context_summarized_event: dict | None


