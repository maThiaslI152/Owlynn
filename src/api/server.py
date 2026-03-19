"""
FastAPI Backend Server for Local Cowork Agent.

This module defines the API endpoints and WebSocket handlers for interacting
with the LangGraph agent, managing user profiles, and serving the frontend.
It supports streaming responses and handling multimodal file uploads.
"""

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, File, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import json
import asyncio
import os
from langchain_core.messages import HumanMessage, AIMessage, ToolMessage

from src.agent.graph import init_agent
from src.memory.user_profile import get_profile, update_profile
from src.memory.persona import get_persona, update_persona_field
from src.memory.memory_manager import load_memories, save_memory, delete_memory
from src.memory.project import project_manager
from src.config.settings import WORKSPACE_DIR

def get_project_workspace(project_id: str = "default") -> str:
    if not project_id or project_id == "null" or project_id == "undefined":
         project_id = "default"
    path = os.path.abspath(os.path.join(WORKSPACE_DIR, "projects", project_id))
    os.makedirs(path, exist_ok=True)
    return path
from src.api.file_processor import start_watcher

from contextlib import asynccontextmanager

connected_websockets = set()

def notify_file_processed(filename, status="processed"):
    """Callback for FileWatcher background thread to broadcast over websockets."""
    import asyncio
    loop = getattr(app.state, "loop", None)
    if not loop:
        print("[Watcher] Loop not preserved, cannot notify websocket clients.")
        return
        
    for ws in list(connected_websockets):
        try:
            coro = ws.send_json({"type": "file_status", "name": filename, "status": status})
            asyncio.run_coroutine_threadsafe(coro, loop)
        except Exception as e:
            print(f"[Watcher] Failed to send ws notification: {e}")

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Preserve loop for async dispatchs from sync threads
    app.state.loop = asyncio.get_running_loop()
    
    # Initialize the LangGraph Agent Engine Singleton asynchronously
    app.state.agent = await init_agent()
    app.state.sessions = {} # thread_id -> GraphSession
    
    # Start background file watcher with WebSocket callback
    try:
        app.state.file_watcher = start_watcher(WORKSPACE_DIR, on_processed_callback=notify_file_processed)
    except Exception as e:
        print(f"[Lifespan] Failed to start file watcher: {e}")
        app.state.file_watcher = None
        
    yield
    # Cleanup: cancel all background tasks
    if getattr(app.state, "file_watcher", None):
        try:
            app.state.file_watcher.stop()
            app.state.file_watcher.join()
        except Exception:
            pass
            
    for session in app.state.sessions.values():
        if session.task:
            session.task.cancel()

app = FastAPI(title="Local Cowork Agent API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve the frontend static files
FRONTEND_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "frontend")

@app.get("/")
async def serve_ui():
    return FileResponse(os.path.join(FRONTEND_DIR, "index.html"))

# Mount the frontend dir for other static assets (script.js, etc)
app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")

# We also need script.js served at root level (since index.html uses src="script.js")
@app.get("/script.js")
async def serve_script():
    return FileResponse(os.path.join(FRONTEND_DIR, "script.js"))

# ─── REST API endpoints ──────────────────────────────────────────────────────

@app.get("/api/profile")
async def api_get_profile():
    return get_profile()

@app.post("/api/profile")
async def api_update_profile(body: dict):
    for field, value in body.items():
        try:
            update_profile(field, value)
        except Exception:
            pass
    return get_profile()

@app.get("/api/persona")
async def api_get_persona():
    return get_persona()

@app.post("/api/persona")
async def api_update_persona(body: dict):
    for field, value in body.items():
        try:
            update_persona_field(field, value)
        except Exception:
            pass
    return get_persona()

@app.get("/api/memories")
async def api_get_memories():
    return load_memories()

@app.post("/api/memories")
async def api_add_memory(body: dict):
    fact = body.get("fact")
    if not fact:
        return {"status": "error", "message": "Fact required"}
    result = save_memory(fact)
    return {"status": "ok", "message": result, "memories": load_memories()}

@app.delete("/api/memories")
async def api_delete_memory(body: dict):
    fact = body.get("fact")
    if not fact:
        return {"status": "error", "message": "Fact required"}
    success = delete_memory(fact)
    return {"status": "ok" if success else "error", "memories": load_memories()}

@app.get("/api/projects")
async def api_list_projects():
    return project_manager.list_projects()

@app.post("/api/projects")
async def api_create_project(body: dict):
    name = body.get("name", "New Project")
    instructions = body.get("instructions")
    return project_manager.create_project(name, instructions)

@app.get("/api/projects/{project_id}")
async def api_get_project(project_id: str):
    return project_manager.get_project(project_id)

@app.post("/api/projects/{project_id}/chats")
async def api_add_project_chat(project_id: str, body: dict):
    # body: {id, name}
    import time
    project_manager.add_chat_to_project(project_id, {
        "id": body["id"],
        "name": body.get("name", "New Chat"),
        "created_at": time.time()
    })
    return {"status": "ok"}

@app.delete("/api/projects/{project_id}/chats/{chat_id}")
async def api_delete_project_chat(project_id: str, chat_id: str):
    project_manager.delete_chat_from_project(project_id, chat_id)
    return {"status": "ok"}

@app.put("/api/projects/{project_id}/chats/{chat_id}")
async def api_update_project_chat(project_id: str, chat_id: str, body: dict):
    project_manager.update_chat_in_project(project_id, chat_id, **body)
    return {"status": "ok"}

@app.get("/api/tools")
async def api_get_tools():
    """Returns a list of available tools for the Customize view."""
    from src.tools import tool_registry
    tools = []
    for name, tool in tool_registry.items():
        desc = getattr(tool, "description", "")
        if not desc and hasattr(tool, "__doc__") and tool.__doc__:
            desc = tool.__doc__.strip().split("\n")[0]
        tools.append({
            "name": name, 
            "description": desc or "No description available.",
            "type": "core" # or plugin
        })
    return tools

@app.get("/api/artifacts")
async def api_get_artifacts(project_id: str = "default"):
    """Returns a list of artifacts. Mocked for design demonstration."""
    # In a full impl, we would read from `{workspace}/.artifacts/`
    return [
        {
            "id": "1",
            "name": "Writing editor",
            "type": "editor",
            "category": "Learn something",
            "image_url": "https://images.unsplash.com/photo-1455390582262-044cdead277a?w=400&auto=format&fit=crop&q=60",
            "description": "Use 'I' instead of 'me' as the subject."
        },
        {
            "id": "2",
            "name": "PRD To Prototype",
            "type": "prototype",
            "category": "Life hacks",
            "image_url": "https://images.unsplash.com/photo-1507238691740-187a5b1d37b8?w=400&auto=format&fit=crop&q=60",
            "description": "Convert PRD to visual design dashboard."
        },
        {
            "id": "3",
            "name": "Slack Project Insights",
            "type": "insights",
            "category": "Play a game",
            "image_url": "https://images.unsplash.com/photo-1563986768609-322da13575f3?w=400&auto=format&fit=crop&q=60",
            "description": "Summarize insights from project slack dumps."
        },
        {
            "id": "4",
            "name": "CodeVerter",
            "type": "converter",
            "category": "Be creative",
            "image_url": "https://images.unsplash.com/photo-1517694712202-14dd9538aa97?w=400&auto=format&fit=crop&q=60",
            "description": "Convert Python to Javascript logic."
        }
    ]

@app.get("/api/files")
async def api_list_files(sub_path: str = "", project_id: str = "default"):
    """Returns a list of files in the workspace with processing status and folder support."""
    try:
        import urllib.parse
        sub_path = urllib.parse.unquote(sub_path)
        
        base_dir = get_project_workspace(project_id)
        target_dir = os.path.abspath(os.path.join(base_dir, sub_path))
        if not target_dir.startswith(os.path.abspath(base_dir)):
             return {"status": "error", "message": "Access denied"}
             
        files = []
        if not os.path.exists(target_dir):
            return []
            
        processed_dir = os.path.join(base_dir, ".processed")
        root_processed_dir = os.path.join(str(WORKSPACE_DIR), ".processed")  # Legacy watcher cache location
        
        for f in os.listdir(target_dir):
            if f.startswith(".") or f == "__pycache__":
                continue
            filepath = os.path.join(target_dir, f)
            stats = os.stat(filepath)
            
            # Identify if item is Folder or File
            is_dir = os.path.isdir(filepath)
            
            # File extraction status cache check (project-local or root watcher cache)
            has_cache = False
            if not is_dir:
                 has_cache = (
                     os.path.exists(os.path.join(processed_dir, f + ".txt")) or
                     os.path.exists(os.path.join(processed_dir, f + ".md")) or
                     os.path.exists(os.path.join(root_processed_dir, f + ".txt")) or
                     os.path.exists(os.path.join(root_processed_dir, f + ".md"))
                 )
                           
            files.append({
                "name": f,
                "size": stats.st_size if not is_dir else 0,
                "modified": stats.st_mtime,
                "type": "folder" if is_dir else "file",
                "status": "processed" if has_cache else "idle"
            })
        return sorted(files, key=lambda x: (x["type"] == "file", x["name"].lower()))
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.get("/api/files/{filename}")
async def api_get_file(filename: str, sub_path: str = "", project_id: str = "default"):
    """Serve/View a file from the workspace."""
    import urllib.parse
    filename = urllib.parse.unquote(filename)
    sub_path = urllib.parse.unquote(sub_path)
    
    base_dir = get_project_workspace(project_id)
    target_dir = os.path.abspath(os.path.join(base_dir, sub_path))
    if not target_dir.startswith(os.path.abspath(base_dir)):
         return {"status": "error", "message": "Access denied"}
         
    filepath = os.path.abspath(os.path.join(target_dir, filename))
    if not filepath.startswith(os.path.abspath(base_dir)):
         return {"status": "error", "message": "Access denied"}
    if not os.path.exists(filepath):
         return {"status": "error", "message": "File not found"}
    return FileResponse(filepath)

@app.delete("/api/files/{filename}")
async def api_delete_file(filename: str, sub_path: str = "", project_id: str = "default"):
    """Deletes a file and its processed cache from the workspace."""
    try:
        import urllib.parse
        filename = urllib.parse.unquote(filename)
        sub_path = urllib.parse.unquote(sub_path)
        
        base_dir = get_project_workspace(project_id)
        target_dir = os.path.abspath(os.path.join(base_dir, sub_path))
        if not target_dir.startswith(os.path.abspath(base_dir)):
             return {"status": "error", "message": "Access denied"}
             
        filepath = os.path.abspath(os.path.join(target_dir, filename))
        if not filepath.startswith(os.path.abspath(base_dir)):
             return {"status": "error", "message": "Access denied"}
        if os.path.exists(filepath):
            if os.path.isdir(filepath):
                 import shutil
                 shutil.rmtree(filepath) # Support deleting folders recursively!
            else:
                 os.remove(filepath)
            
        # Clean up cache
        processed_dir = os.path.join(base_dir, ".processed")
        for cache_ext in [".txt", ".md"]:
            cache_path = os.path.join(processed_dir, filename + cache_ext)
            if os.path.exists(cache_path):
                os.remove(cache_path)
                
        # Broadcast removal to websocket
        notify_file_processed(filename, status="deleted")
        return {"status": "ok", "message": f"Deleted {filename}"}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.post("/api/files/{filename}/rename")
async def api_rename_file(filename: str, body: dict):
    """Renames a file in the workspace."""
    try:
        import urllib.parse
        filename = urllib.parse.unquote(filename)
        new_name = body.get("new_name")
        sub_path = urllib.parse.unquote(body.get("sub_path", ""))
        project_id = body.get("project_id", "default")
        
        if not new_name:
             return {"status": "error", "message": "new_name is required"}
             
        base_dir = get_project_workspace(project_id)
        target_dir = os.path.abspath(os.path.join(base_dir, sub_path))
        if not target_dir.startswith(os.path.abspath(base_dir)):
             return {"status": "error", "message": "Access denied"}
             
        old_path = os.path.abspath(os.path.join(target_dir, filename))
        new_path = os.path.abspath(os.path.join(target_dir, new_name))
        if not old_path.startswith(os.path.abspath(base_dir)) or not new_path.startswith(os.path.abspath(base_dir)):
             return {"status": "error", "message": "Access denied"}
        
        if not os.path.exists(old_path):
             return {"status": "error", "message": "File not found"}
        if os.path.exists(new_path):
             return {"status": "error", "message": "File with new name already exists"}
             
        os.rename(old_path, new_path)
        
        # Rename cache too
        processed_dir = os.path.join(base_dir, ".processed")
        for cache_ext in [".txt", ".md"]:
             old_cache = os.path.join(processed_dir, filename + cache_ext)
             new_cache = os.path.join(processed_dir, new_name + cache_ext)
             if os.path.exists(old_cache):
                 os.rename(old_cache, new_cache)
                 
        notify_file_processed(filename, status="deleted")
        notify_file_processed(new_name, status="processed")
        
        return {"status": "ok", "message": f"Renamed to {new_name}"}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.post("/api/files/{filename}/move")
async def api_move_file(filename: str, body: dict):
    """Moves a file or folder into another subdirectory within the project workspace."""
    try:
        import urllib.parse
        filename = urllib.parse.unquote(filename)
        current_sub_path = urllib.parse.unquote(body.get("current_sub_path", ""))
        target_sub_path = urllib.parse.unquote(body.get("target_sub_path", ""))
        project_id = body.get("project_id", "default")
        
        base_dir = get_project_workspace(project_id)
        src_dir = os.path.abspath(os.path.join(base_dir, current_sub_path))
        dst_dir = os.path.abspath(os.path.join(base_dir, target_sub_path))
        
        if not src_dir.startswith(os.path.abspath(base_dir)) or not dst_dir.startswith(os.path.abspath(base_dir)):
             return {"status": "error", "message": "Access denied"}
             
        old_path = os.path.abspath(os.path.join(src_dir, filename))
        new_path = os.path.abspath(os.path.join(dst_dir, filename))
        if not old_path.startswith(os.path.abspath(base_dir)) or not new_path.startswith(os.path.abspath(base_dir)):
             return {"status": "error", "message": "Access denied"}
        
        if not os.path.exists(old_path):
             return {"status": "error", "message": f"Source file not found: {filename}"}
        if os.path.exists(new_path):
             return {"status": "error", "message": "Destination already contains an item with this name"}
             
        os.rename(old_path, new_path)
        return {"status": "ok", "message": f"Moved {filename} to {target_sub_path}"}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.post("/api/upload")
async def api_upload_file(file: UploadFile = File(...), sub_path: str = "", project_id: str = "default"):
    """Saves a file directly to the workspace bypassing the graph."""
    try:
        import urllib.parse
        sub_path = urllib.parse.unquote(sub_path)
        base_dir = get_project_workspace(project_id)
        
        target_dir = os.path.abspath(os.path.join(base_dir, sub_path))
        if not target_dir.startswith(os.path.abspath(base_dir)):
             return {"status": "error", "message": "Access denied"}
             
        if not os.path.exists(target_dir):
            os.makedirs(target_dir, exist_ok=True)
            
        filepath = os.path.abspath(os.path.join(target_dir, file.filename))
        if not filepath.startswith(os.path.abspath(base_dir)):
             return {"status": "error", "message": "Access denied"}
        with open(filepath, "wb") as f:
            f.write(await file.read())
        return {"status": "ok", "message": f"Uploaded {file.filename}"}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.post("/api/folders")
async def api_create_folder(body: dict):
    """Creates a new directory in the workspace."""
    try:
        import urllib.parse
        name = body.get("name")
        sub_path = urllib.parse.unquote(body.get("sub_path", ""))
        project_id = body.get("project_id", "default")
        
        if not name:
             return {"status": "error", "message": "Folder name is required"}
             
        base_dir = get_project_workspace(project_id)
        target_dir = os.path.abspath(os.path.join(base_dir, sub_path, name))
        if not target_dir.startswith(os.path.abspath(base_dir)):
             return {"status": "error", "message": "Access denied"}
             
        if os.path.exists(target_dir):
             return {"status": "error", "message": "Folder already exists"}
             
        os.makedirs(target_dir, exist_ok=True)
        return {"status": "ok", "message": f"Created folder {name}"}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.delete("/api/projects/{project_id}")
async def api_delete_project(project_id: str):
    success = project_manager.delete_project(project_id)
    if success:
        return {"status": "ok"}
    else:
        return {"status": "error", "message": "Failed to delete project or cannot delete default project"}



@app.get("/api/history/{thread_id}")
async def api_get_history(thread_id: str):
    """Retrieves full chat history for a specific thread from Redis."""
    try:
        agent = app.state.agent
        if not agent:
            return []
            
        config = {"configurable": {"thread_id": thread_id}}
        state = await agent.aget_state(config)
        
        if not state or not state.values:
            return []
            
        messages = state.values.get("messages", [])
        return [serialize_message(m) for m in messages]
    except Exception as e:
        print(f"Failed to fetch history: {e}")
        return []


@app.put("/api/projects/{project_id}")
async def api_update_project(project_id: str, body: dict):
    return project_manager.update_project(project_id, **body)


def serialize_message(msg):
    """
    Converts Langchain BaseMessage objects into raw UI-friendly dictionaries
    so they can be safely streamed over WebSockets to a React client.
    """
    serialized = {"type": msg.type, "content": msg.content}
    
    if isinstance(msg, AIMessage) and getattr(msg, "tool_calls", None):
        serialized["tool_calls"] = msg.tool_calls
        
    if isinstance(msg, ToolMessage):
        serialized["tool_name"] = msg.name
        serialized["tool_call_id"] = msg.tool_call_id
        # Truncate content for UI readability/performance if too large
        if isinstance(msg.content, str) and len(msg.content) > 500:
            serialized["content"] = msg.content[:500] + "\n\n... [Content Truncated for UI] ..."
            
    return serialized


class GraphSession:
    """Manages the graph execution for a specific thread in a background task."""
    def __init__(self, thread_id, agent, sessions_registry):
        self.thread_id = thread_id
        self.agent = agent
        self.sessions_registry = sessions_registry
        self.listeners = set() # asyncio.Queues
        self.task = None
        self.event_buffer = [] # Store all events for the current turn
        self.is_running = False

    async def add_listener(self):
        q = asyncio.Queue()
        self.listeners.add(q)
        # Replay all events of the current turn to catch up
        for event in self.event_buffer:
            await q.put(event)
        return q

    def remove_listener(self, q: asyncio.Queue):
        self.listeners.discard(q)

    def is_active(self):
        return self.is_running or len(self.listeners) > 0

    async def start_run(self, input_data, config):
        if self.is_running:
            return
        self.event_buffer = []
        self.is_running = True
        self.task = asyncio.create_task(self._execute(input_data, config))

    async def _execute(self, input_data, config):
        try:
            # Initial status
            start_msg = {"type": "status", "content": "reasoning"}
            self.event_buffer.append(start_msg)
            for q in list(self.listeners):
                await q.put(start_msg)

            async for event in self.agent.astream_events(input_data, config=config, version="v2"):
                self.event_buffer.append(event)
                # Broadcast
                for q in list(self.listeners):
                    await q.put(event)
        except Exception as e:
            import traceback
            traceback.print_exc()
            err_msg = {"type": "error", "content": f"Graph Execution Error: {str(e)}"}
            self.event_buffer.append(err_msg)
            for q in list(self.listeners):
                await q.put(err_msg)
        finally:
            self.is_running = False
            # Final status update
            done_msg = {"type": "status", "content": "idle"}
            print(f"[WS Debug] GraphSession._execute for thread {self.thread_id} FINISHED. Putting done_msg.")
            self.event_buffer.append(done_msg)
            for q in list(self.listeners):
                await q.put(done_msg)

            
            # If no one is listening anymore, remove from registry
            if not self.listeners and self.thread_id in self.sessions_registry:
                del self.sessions_registry[self.thread_id]


@app.websocket("/ws/chat/{thread_id}")
async def websocket_endpoint(websocket: WebSocket, thread_id: str):
    await websocket.accept()
    connected_websockets.add(websocket) # Track connection
    
    config = {"configurable": {"thread_id": thread_id}}
    agent = websocket.app.state.agent
    
    if not agent:
        await websocket.close(code=1008, reason="Agent not initialized")
        return

    # Get or create session
    sessions = websocket.app.state.sessions
    if thread_id not in sessions:
        sessions[thread_id] = GraphSession(thread_id, agent, sessions)
    session = sessions[thread_id]

    # Task to listen to the session events and send them to the websocket
    async def forward_events():
        q = await session.add_listener()
        try:
            while True:
                event = await q.get()
                if event is None: # Sentinel
                    break
            
                # Handle standard LangGraph events vs our custom wrapped events
                if isinstance(event, dict) and "event" in event:
                    kind = event.get("event")
                    metadata = event.get("metadata", {})
                    node = metadata.get("langgraph_node")
                
                    # Debug print
                    if kind in ["on_chain_start", "on_chain_end"]:
                        print(f"[WS Debug] Event={kind} | Node={node}")

                    if kind == "on_chat_model_stream" and node in ["simple", "complex", "tool_executor"]:
                        chunk = event["data"]["chunk"]
                        if chunk.content:
                            await websocket.send_json({"type": "chunk", "content": chunk.content})
                        
                    elif kind == "on_chain_end":
                        if node in ["simple", "complex", "tool_executor"]:
                            output = event["data"]["output"]
                            if isinstance(output, dict) and "messages" in output:
                                msg = output["messages"][0]
                                if getattr(msg, "tool_calls", None):
                                    await websocket.send_json({"type": "message", "message": serialize_message(msg)})
                        elif node == "tools" or metadata.get("langgraph_step") == "tools":
                            output = event["data"]["output"]
                            if isinstance(output, dict) and "messages" in output:
                                for msg in output["messages"]:
                                    await websocket.send_json({"type": "message", "message": serialize_message(msg)})
                else:
                    # Our custom events (status, error, etc)
                    print(f"[WS Debug] Custom Event: {event}")
                    await websocket.send_json(event)
        except WebSocketDisconnect:
            print("[WS Debug] Forwarder disconnected")
            pass
        except Exception as e:
            import traceback
            print(f"Error in event forwarder: {e}")
            traceback.print_exc()
        finally:
            session.remove_listener(q)
            # Guarantee the frontend returns to idle state on finish or crash
            try:
                await websocket.send_json({"type": "status", "content": "idle"})
            except Exception:
                pass
            if not session.is_active() and thread_id in sessions:
                del sessions[thread_id]



    # Start the event forwarder task
    forwarder_task = asyncio.create_task(forward_events())

    try:
        while True:
            data = await websocket.receive_text()
            try:
                payload = json.loads(data)
            except json.JSONDecodeError:
                continue

            # Handle explicit STOP command to cancel executing GraphSession
            if payload.get("type") == "stop":
                sessions = websocket.app.state.sessions
                if thread_id in sessions:
                    session = sessions[thread_id]
                    if session.task and not session.task.done():
                        session.task.cancel()
                        session.is_running = False
                continue

            user_input = payload.get("message", "")
            files = payload.get("files", [])
            payload_mode = payload.get("mode", "tools_on")
            project_id = payload.get("project_id", "default")
            base_dir = get_project_workspace(project_id)

            # Handle Workspace References
            for f in files:
                if f.get("type") == "workspace_ref":
                    prompt_path = f.get("path")
                    user_input += f"\n\n[Attached Workspace File: {prompt_path}]"

            # Save uploaded files into the agent workspace so tools can read them
            for f in files:
                if f.get("type") == "workspace_ref":
                    continue # Skip saving workspace references they already exist on disk
                name = f.get("name")
                data_b64 = f.get("data")
                if name and data_b64:
                    try:
                        import base64
                        import urllib.parse
                        raw_bytes = base64.b64decode(data_b64)
                        
                        safe_name = urllib.parse.unquote(name).lstrip("/")
                        filepath = os.path.abspath(os.path.join(base_dir, safe_name))
                        if not filepath.startswith(os.path.abspath(base_dir)):
                             print(f"[Workspace] Access denied for file {name} (outside workspace)")
                             continue
                             
                        with open(filepath, "wb") as file_out:
                            file_out.write(raw_bytes)
                        print(f"[Workspace] Saved file to {filepath}")
                    except Exception as e:
                        print(f"[Workspace] Failed to save file {name}: {e}")

            message_content = await build_message_content(user_input, files)
            if not message_content:
                continue

            # Start the graph run in the session (background)
            await session.start_run(
                {
                    "messages": [HumanMessage(content=message_content)],
                    "mode": payload_mode,
                    "project_id": project_id
                },
                config=config
            )

    except WebSocketDisconnect:
        print(f"Client disconnected from thread: {thread_id}")
    finally:
        # We don't cancel the session task here! It continues in background.
        connected_websockets.discard(websocket) # Remove from active list
        # But we should stop the forwarder.
        forwarder_task.cancel()
        # The forwarder cleanup will check if it should delete the session.


async def build_message_content(text: str, files: list):
    """
    Builds the message content block for LangChain, supporting:
    - Images: forwarded as image_url for multimodal Qwen2-VL
    - Text PDFs: text extracted via PyMuPDF and injected
    - Scanned PDFs: each page rendered as image and forwarded to the vision model
    - Code/text files: decoded and injected as a fenced code block
    """
    import base64
    from io import BytesIO
    
    content_parts = []
    text_injections = []
    has_multimodal = False

    for f in files:
        mime = f.get("type", "")
        data_b64 = f.get("data", "")
        name = f.get("name", "file")
        
        try:
            raw_bytes = base64.b64decode(data_b64)
        except Exception:
            continue
        
        if mime.startswith("image/"):
            # Regular image — forward directly to vision model
            has_multimodal = True
            content_parts.append({
                "type": "image_url",
                "image_url": {"url": f"data:{mime};base64,{data_b64}"}
            })
        
        elif mime == "application/pdf" or name.lower().endswith(".pdf"):
            print(f"[PDF] Uploaded '{name}'. Adding workspace reference.")
            # Notify the agent the file is in the workspace and readable via tool
            text_injections.append(f"[File: {name} uploaded to workspace. Use `read_workspace_file` tool to read it if needed.]")
            
            # Optional: Visual Layer only if multimodal (for backward compatibility or graphics)
            # composite_b64 = await asyncio.to_thread(render_pdf_as_composite, raw_bytes)
            # if composite_b64:
            #     has_multimodal = True
            #     content_parts.append({
            #         "type": "text",
            #         "text": f"[File: {name}] Visual Layout (pages stitched into one continuous image below):"
            #     })
            #     content_parts.append({
            #         "type": "image_url",
            #         "image_url": {"url": f"data:image/jpeg;base64,{composite_b64}"}
            #     })

        else:
            # Text / code file
            print(f"[File] Uploaded '{name}'. Adding workspace reference.")
            text_injections.append(f"[File: {name} uploaded to workspace. Use `read_workspace_file` tool to read it if needed.]")


    # Build final content
    if has_multimodal:
        # Multimodal message — prepend any text file injections
        for inj in text_injections:
            content_parts.insert(0, {"type": "text", "text": inj})
        if text:
            content_parts.append({"type": "text", "text": text})
        return content_parts if content_parts else None
    else:
        # Plain text message
        parts = text_injections[:]
        if text:
            parts.append(text)
        return "\n\n".join(parts) if parts else None


def extract_pdf_text(raw_bytes: bytes) -> str:
    """Extract text from a PDF using PyMuPDF."""
    try:
        import fitz  # PyMuPDF
        doc = fitz.open(stream=raw_bytes, filetype="pdf")
        pages_text = []
        for page in doc:
            pages_text.append(page.get_text())
        return "\n\n".join(pages_text)
    except Exception as e:
        print(f"[PDF] PyMuPDF text extraction failed: {e}")
        return ""


def render_pdf_as_composite(raw_bytes: bytes, max_pages: int = 10) -> str | None:
    """
    Render ALL PDF pages and stitch them into a single tall composite JPEG.
    
    Since mlx_vlm Qwen2-VL has a bug processing multiple separate image_url entries,
    we sidestep the issue by combining all pages into ONE image. The model can still
    see and read all pages in a single pass.
    
    Constraints:
    - Each page is scaled to a fixed width of 392px (14×28 — a known-safe patch width)
    - Heights are rounded to nearest multiple of 28
    - Pages separated by a thin white divider line for visual clarity
    - Final composite W and H must both be multiples of 28
    
    Returns: base64-encoded JPEG string, or None on failure.
    """
    PATCH_SIZE = 28
    PAGE_WIDTH = 392   # 14 × 28 — safe patch count (28 horizontal patches)
    DIVIDER_H = 28     # Thin white separator between pages (must be multiple of 28)
    
    try:
        import fitz
        import base64
        from PIL import Image, ImageDraw
        from io import BytesIO
        
        doc = fitz.open(stream=raw_bytes, filetype="pdf")
        page_imgs = []
        
        for i, page in enumerate(doc):
            if i >= max_pages:
                break
            
            # Render at 1x
            pix = page.get_pixmap(matrix=fitz.Matrix(1.0, 1.0), alpha=False)
            img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
            
            # Scale to fixed width, preserve aspect ratio
            w, h = img.size
            scale = PAGE_WIDTH / w
            new_h = int(h * scale)
            # Snap height to multiple of 28
            new_h = max(PATCH_SIZE, (new_h // PATCH_SIZE) * PATCH_SIZE)
            img = img.resize((PAGE_WIDTH, new_h), Image.LANCZOS)
            page_imgs.append(img)
            print(f"[PDF] Rendered page {i+1} as {PAGE_WIDTH}x{new_h}")
        
        if not page_imgs:
            return None
        
        # Stitch pages vertically with dividers
        divider = Image.new("RGB", (PAGE_WIDTH, DIVIDER_H), color=(220, 220, 220))
        total_h = sum(img.height for img in page_imgs) + DIVIDER_H * (len(page_imgs) - 1)
        # Snap total height to multiple of 28
        total_h = max(PATCH_SIZE, (total_h // PATCH_SIZE) * PATCH_SIZE)
        
        composite = Image.new("RGB", (PAGE_WIDTH, total_h), color=(255, 255, 255))
        y = 0
        for i, img in enumerate(page_imgs):
            composite.paste(img, (0, y))
            y += img.height
            if i < len(page_imgs) - 1:
                composite.paste(divider, (0, y))
                y += DIVIDER_H
        
        # Encode final composite
        buf = BytesIO()
        composite.save(buf, format="JPEG", quality=85)
        b64 = base64.b64encode(buf.getvalue()).decode()
        print(f"[PDF] Composite image: {PAGE_WIDTH}x{total_h} ({len(page_imgs)} pages)")
        return b64
        
    except Exception as e:
        print(f"[PDF] Composite rendering failed: {e}")
        return None


def extract_text_file(name: str, mime: str, raw_bytes: bytes) -> str:
    """Decode a plain text or code file from raw bytes."""
    text_mimes = ["text/", "application/json", "application/xml", "application/javascript"]
    text_exts = [".py", ".js", ".ts", ".txt", ".md", ".csv", ".yaml", ".yml", ".sh", ".json", ".toml"]
    is_text = any(mime.startswith(m) for m in text_mimes) or any(name.lower().endswith(e) for e in text_exts)
    if is_text:
        try:
            return raw_bytes.decode("utf-8", errors="replace")[:8000]
        except Exception:
            return ""
    return ""
