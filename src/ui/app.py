"""
Streamlit UI for the Local Cowork Agent.

This module provides an alternative or older user interface built with Streamlit
for chatting with the agent and streaming reasoning/tool execution steps.
"""

import streamlit as st
import uuid
import asyncio
from langchain_core.messages import HumanMessage, AIMessage, ToolMessage
from src.agent.graph import init_agent

# Initialize standard styling and agent
st.set_page_config(page_title="Local Cowork Agent", layout="wide")
st.title("🧠 Local Cowork Agent (M4 native)")

if "thread_id" not in st.session_state:
    st.session_state.thread_id = str(uuid.uuid4())

# Initialize the LangGraph Application exactly once
@st.cache_resource
def get_agent():
    # Since init_agent is async, we use asyncio.run to initialize it synchronously 
    # for Streamlit's cache_resource.
    try:
        return asyncio.run(init_agent())
    except RuntimeError:
        # Fallback for when an event loop is already running
        loop = asyncio.get_event_loop()
        return loop.run_until_complete(init_agent())

app = get_agent()

# Initialize chat history in UI
if "chat_history" not in st.session_state:
    st.session_state.chat_history = []

for msg in st.session_state.chat_history:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

user_input = st.chat_input("Ask the agent to do something in the workspace...")

if user_input:
    # Display human prompt in UI
    with st.chat_message("user"):
        st.markdown(user_input)
    st.session_state.chat_history.append({"role": "user", "content": user_input})
    
    # Configure graph thread for Redis checkpointing
    config = {"configurable": {"thread_id": st.session_state.thread_id}}
    
    with st.spinner("Agent is reasoning..."):
        # Stream the graph execution node-by-node
        graph_stream = app.stream(
            {"messages": [HumanMessage(content=user_input)]}, 
            config=config, 
            stream_mode="values"
        )
        
        # We will capture the final assistant message or tool calls to display in UI
        final_message = ""
        
        for state in graph_stream:
            # state is the AgentState dict at this step
            if "messages" not in state or not state["messages"]:
                continue
                
            latest_msg = state["messages"][-1]
            
            # Print tool calls cleanly 
            if getattr(latest_msg, "tool_calls", None):
                for tc in latest_msg.tool_calls:
                    st.toast(f"🛠️ Executing Tool: {tc['name']}")
                    st.session_state.chat_history.append({
                        "role": "assistant (tool)", 
                        "content": f"🛠️ **Executing Tool:** `{tc['name']}`\n```json\n{tc['args']}\n```"
                    })
                    with st.chat_message("assistant (tool)"):
                        st.markdown(f"🛠️ **Executing Tool:** `{tc['name']}`\n```json\n{tc['args']}\n```")
                        
            # Print Tool Results cleanly
            elif isinstance(latest_msg, ToolMessage):
                st.session_state.chat_history.append({
                    "role": "tool",
                    "content": f"✅ **Tool Result:**\n```\n{latest_msg.content[:500]}{'...' if len(latest_msg.content) > 500 else ''}\n```"
                })
                with st.chat_message("tool"):
                    st.markdown(f"✅ **Tool Result:**\n```\n{latest_msg.content[:500]}{'...' if len(latest_msg.content) > 500 else ''}\n```")
                    
            # Capture final reasoning
            elif isinstance(latest_msg, AIMessage) and latest_msg.content:
                final_message = latest_msg.content
        
        # Display the final AI text response to the user
        if final_message:
            st.session_state.chat_history.append({"role": "assistant", "content": final_message})
            with st.chat_message("assistant"):
                st.markdown(final_message)
                
# Sidebar Controls
with st.sidebar:
    st.header("⚙️ Agent Controls")
    st.write(f"**Current Thread ID:** `{st.session_state.thread_id}`")
    if st.button("Start New Task (Clear Thread)"):
        st.session_state.thread_id = str(uuid.uuid4())
        st.session_state.chat_history = []
        st.rerun()
    
    st.divider()
    st.subheader("Memory")
    st.info("The agent automatically pulls semantic memory via Mem0/ChromaDB and stores thread state in Redis.")
