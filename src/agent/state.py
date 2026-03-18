"""
State Definition for the Local Cowork Agent.

This module defines the `AgentState` TypedDict used by LangGraph to maintain
conversation history, execution mode, and other contextual flags.
"""

import operator
from typing import Annotated, TypedDict, Sequence, Any
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

    # Project ID to associate this conversation with a specific project
    project_id: str | None

    # Track if any tool execution was vetted/approved by security node
    execution_approved: bool | None

    # Routing decision from small model: 'SIMPLE', 'CONTEXT', 'TOOL', 'COMPLEX'
    routing_decision: str | None


