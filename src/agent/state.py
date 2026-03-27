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

    # Routing decision: 'simple' or 'complex'
    route: str | None
    model_used: str | None         # 'small' or 'large'
    memory_context: str | None     # Formatted context string
    persona: str | None            # Persona summary string

    # Secure cyclic tool flow state
    pending_tool_calls: bool | None
    pending_tool_names: Annotated[list[str], operator.add]
    security_decision: str | None  # 'approved' | 'denied'
    security_reason: str | None


