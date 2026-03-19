# Backend Integration Guide for Enhanced Chat Features

## Overview
This guide explains how to modify your backend to fully support the new chat experience improvements.

## 1. Tool Execution Events

### Modify `src/agent/nodes/tool_executor.py`

Add WebSocket events when tools execute:

```python
import time
import json
from langchain_core.messages import ToolMessage

async def tool_executor_node(state: AgentState) -> AgentState:
    """Execute selected tool and emit execution events."""
    tool_name = state.get("selected_tool", "unknown")
    tool_input = state.get("tool_input", "")
    
    try:
        # Optional: Send tool start event
        ws_manager.broadcast({
            "type": "tool_execution",
            "tool_name": tool_name,
            "status": "running",
            "input": json.dumps(tool_input) if isinstance(tool_input, dict) else str(tool_input)
        })
        
        start_time = time.time()
        
        # Execute tool (existing code)
        tool_result = execute_tool(tool_name, tool_input)
        
        duration = time.time() - start_time
        
        # Send tool success event
        ws_manager.broadcast({
            "type": "tool_execution",
            "tool_name": tool_name,
            "status": "success",
            "input": json.dumps(tool_input) if isinstance(tool_input, dict) else str(tool_input),
            "output": str(tool_result)[:2000],  # Truncate long outputs
            "duration": duration
        })
        
        return AgentState(
            messages=[ToolMessage(content=tool_result, tool_call_id=...)],
            tool_result=tool_result
        )
    
    except Exception as e:
        duration = time.time() - start_time
        
        # Send tool error event
        ws_manager.broadcast({
            "type": "tool_execution",
            "tool_name": tool_name,
            "status": "error",
            "input": json.dumps(tool_input) if isinstance(tool_input, dict) else str(tool_input),
            "error": str(e),
            "duration": duration
        })
        
        raise
```

## 2. Model Information

### Modify `src/api/server.py`

Track which model was used and send it to the client:

```python
# Add to your server initialization
app.state.current_model = "unknown"
app.state.small_model = "Qwen2-VL-7B"
app.state.large_model = "your-large-model"

# When sending responses
@app.websocket("/ws/chat/{session_id}")
async def websocket_endpoint(websocket: WebSocket, session_id: str):
    await websocket.accept()
    
    async for message in agent.stream(state):
        # Determine which model was used
        model_used = state.get("model_used", "unknown")
        
        # Send model info
        await websocket.send_json({
            "type": "model_info",
            "model": model_used
        })
        
        # Then send the response chunks
        await websocket.send_json({
            "type": "chunk",
            "content": chunk_text,
            "metadata": {
                "model": model_used,
                "timestamp": datetime.now().isoformat()
            }
        })
```

## 3. Enhanced Error Handling

### Create a utility for structured errors

```python
# src/api/error_handler.py

def send_error(ws_manager, title: str, message: str, details: str = None):
    """Send structured error message to client."""
    ws_manager.broadcast({
        "type": "error",
        "title": title,
        "content": message,
        "details": details
    })

# Usage in your nodes:
async def complex_node(state: AgentState) -> AgentState:
    try:
        result = await llm.invoke(...)
    except ConnectionError as e:
        send_error(
            ws_manager,
            title="LLM Connection Error",
            message="Failed to connect to the language model",
            details=str(e)
        )
        raise
```

## 4. WebSocket Manager Enhancement

### Enhance `src/api/server.py` WebSocket handling

```python
class WebSocketManager:
    def __init__(self):
        self.active_connections = {}
    
    def register(self, session_id: str, websocket: WebSocket):
        if session_id not in self.active_connections:
            self.active_connections[session_id] = []
        self.active_connections[session_id].append(websocket)
    
    async def broadcast(self, session_id: str, message: dict):
        """Send message to all clients in a session."""
        if session_id not in self.active_connections:
            return
        
        for connection in self.active_connections[session_id]:
            try:
                await connection.send_json(message)
            except Exception as e:
                print(f"Error sending message: {e}")
    
    def disconnect(self, session_id: str, websocket: WebSocket):
        if session_id in self.active_connections:
            self.active_connections[session_id].remove(websocket)

manager = WebSocketManager()

@app.websocket("/ws/chat/{session_id}")
async def websocket_endpoint(websocket: WebSocket, session_id: str):
    await websocket.accept()
    manager.register(session_id, websocket)
    
    try:
        while True:
            # Your stream logic
            await manager.broadcast(session_id, {
                "type": "chunk",
                "content": text_chunk
            })
    finally:
        manager.disconnect(session_id, websocket)
```

## 5. Response Metadata Structure

### Standard response message format

```python
# For streaming chunks
{
    "type": "chunk",
    "content": "token-by-token text",
    "metadata": {
        "model": "Qwen2-VL-7B",
        "token_count": 150,
        "chunk_index": 1,
        "timestamp": "2026-03-20T10:30:00Z"
    }
}

# For tool execution
{
    "type": "tool_execution",
    "tool_name": "web_search",
    "status": "running|success|error",
    "input": "search query or JSON",
    "output": "result or null",
    "error": "error message or null",
    "duration": 1.234
}

# For model info
{
    "type": "model_info",
    "model": "Qwen2-VL-7B",
    "model_type": "small|large",
    "reasoning_depth": 0.8,
    "thinking_enabled": true
}

# For errors
{
    "type": "error",
    "title": "Connection Error",
    "content": "Failed to reach API endpoint",
    "details": "Connection timeout after 30 seconds",
    "error_code": "TIMEOUT_ERROR"
}

# For status updates
{
    "type": "status",
    "content": "Analyzing query...",
    "status_code": "analyzing|thinking|executing|complete"
}
```

## 6. Update Agent State

### Modify `src/agent/state.py` if needed

```python
class AgentState(TypedDict):
    messages: Annotated[Sequence[BaseMessage], add_messages]
    model_used: str | None  # Track which model is being used
    thinking_enabled: bool | None
    extraction_depth: float | None  # How deep to think
    tool_execution_log: list[dict] | None  # Track tool calls
    reasoning_depth: float | None
    # ... existing fields
```

## 7. Router Node Enhancement

### Improve `src/agent/nodes/router.py`

Track and send model routing decisions:

```python
async def router_node(state: AgentState) -> AgentState:
    """Route to appropriate handler and track model choice."""
    
    # Determine routing
    if simple_query(state):
        model = "small"
        route = "simple"
    else:
        model = "large"
        route = "complex"
    
    # Send model info to client
    ws_manager.broadcast(session_id, {
        "type": "model_info",
        "model": model,
        "route": route
    })
    
    return {**state, "model_used": model, "route": route}
```

## 8. Complete WebSocket Example

```python
@app.websocket("/ws/chat/{session_id}")
async def websocket_endpoint(websocket: WebSocket, session_id: str):
    await websocket.accept()
    manager.register(session_id, websocket)
    
    try:
        # Get initial message
        data = await websocket.receive_json()
        user_message = data.get("message", "")
        
        # Create initial state
        initial_state = AgentState(
            messages=[HumanMessage(content=user_message)],
            project_id=session_id
        )
        
        # Stream agent responses
        async for event in agent.astream(initial_state):
            # Parse different event types
            if isinstance(event, dict):
                if "tool_execution" in event:
                    await manager.broadcast(session_id, {
                        "type": "tool_execution",
                        **event["tool_execution"]
                    })
                elif "chunk" in event:
                    await manager.broadcast(session_id, {
                        "type": "chunk",
                        "content": event["chunk"],
                        "metadata": event.get("metadata", {})
                    })
                elif "status" in event:
                    await manager.broadcast(session_id, {
                        "type": "status",
                        "content": event["status"]
                    })
        
        # Send completion
        await manager.broadcast(session_id, {
            "type": "status",
            "content": "Complete",
            "status_code": "complete"
        })
    
    except Exception as e:
        await manager.broadcast(session_id, {
            "type": "error",
            "title": "Error",
            "content": str(e)
        })
    
    finally:
        manager.disconnect(session_id, websocket)
```

## Testing the Improvements

### 1. Test Syntax Highlighting
Send a message with code:
```
"Show me a Python example"
```
Verify the code block has syntax highlighting.

### 2. Test Tool Execution Display
Configure a tool to run and watch for the tool execution card.

### 3. Test Error Handling
Try an invalid operation and check error display.

### 4. Test Model Info
Check that model badge appears at bottom of responses.

## Performance Considerations

- Tool execution events should be sent asynchronously
- Truncate long tool outputs (>2000 chars recommended)
- Consider batching multiple small events into one message
- Use streaming for large responses to avoid timeout

## Debugging

Enable debug logging:

```python
# In server.py
import logging
logging.basicConfig(level=logging.DEBUG)

# Then check console logs
```

Monitor WebSocket messages in browser:
```javascript
// In browser console
socket.addEventListener('message', (e) => {
    console.log('Server message:', e.data);
});
```

## Next Steps

1. Implement tool execution events first (highest impact)
2. Add model info tracking
3. Enhance error handling
4. Test all message types
5. Monitor performance
6. Iterate based on user feedback
