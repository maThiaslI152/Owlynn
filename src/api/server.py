"""
FastAPI Backend Server for Local Cowork Agent.

This module defines the API endpoints and WebSocket handlers for interacting
with the LangGraph agent, managing user profiles, and serving the frontend.
It supports streaming responses and handling multimodal file uploads.
"""

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
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
from src.memory.memory_manager import load_memories

from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialize the LangGraph Agent Engine Singleton asynchronously
    app.state.agent = await init_agent()
    yield

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
        
    return serialized

@app.websocket("/ws/chat/{thread_id}")
async def websocket_endpoint(websocket: WebSocket, thread_id: str):
    await websocket.accept()
    config = {"configurable": {"thread_id": thread_id}}
    
    try:
        while True:
            data = await websocket.receive_text()
            
            try:
                payload = json.loads(data)
            except json.JSONDecodeError:
                continue

            user_input = payload.get("message", "")
            files = payload.get("files", [])  # list of {name, type, data (base64)}

            # Build the message content — may be multimodal if image files attached
            message_content = build_message_content(user_input, files)
            if not message_content:
                continue

            await websocket.send_json({"type": "status", "content": "reasoning"})
            
            try:
                agent = websocket.app.state.agent
                if not agent:
                     raise Exception("Agent not initialized")
                     
                payload_mode = payload.get("mode", "reasoning")

                # Use astream_events for token streaming and node updates
                async for event in agent.astream_events(
                    {
                        "messages": [HumanMessage(content=message_content)],
                        "mode": payload_mode
                    },
                    config=config,
                    version="v2"
                ):
                    kind = event.get("event")
                    
                    if kind == "on_chat_model_stream":
                        # Stream tokens in real-time
                        chunk = event["data"]["chunk"]
                        if chunk.content:
                            await websocket.send_json({
                                "type": "chunk",
                                "content": chunk.content
                            })
                            
                    elif kind == "on_chain_end":
                        # Node or chain finished
                        metadata = event.get("metadata", {})
                        node = metadata.get("langgraph_node")
                        
                        if node == "reasoning":
                            output = event["data"]["output"]
                            if isinstance(output, dict) and "messages" in output:
                                msg = output["messages"][0]
                                # Only send full message if it has tool calls (streaming covers text)
                                if getattr(msg, "tool_calls", None):
                                    await websocket.send_json({
                                        "type": "message",
                                        "message": serialize_message(msg)
                                    })
                        elif node == "tools" or metadata.get("langgraph_step") == "tools":
                            output = event["data"]["output"]
                            if isinstance(output, dict) and "messages" in output:
                                for msg in output["messages"]:
                                    await websocket.send_json({
                                        "type": "message",
                                        "message": serialize_message(msg)
                                    })

                await websocket.send_json({"type": "status", "content": "idle"})

            except Exception as e:
                import traceback
                print(f"--- GRAPH EXECUTION ERROR: {e} ---")
                traceback.print_exc()
                
                # Write to log file for easy reading
                try:
                    with open("/Users/tim/Documents/Owlynn/graph_error.log", "w") as f:
                        f.write(f"Error: {e}\n")
                        f.write(traceback.format_exc())
                except Exception as log_err:
                    print(f"Failed to write log file: {log_err}")
                    
                await websocket.send_json({
                    "type": "error",
                    "content": f"Graph Execution Error: {str(e)}"
                })

    except WebSocketDisconnect:
        print(f"Client disconnected from thread: {thread_id}")


def build_message_content(text: str, files: list):
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
            # Try text extraction first with PyMuPDF
            extracted_text = extract_pdf_text(raw_bytes)
            
            if extracted_text and len(extracted_text.strip()) > 100:
                # Good text-based PDF — inject as text block
                text_injections.append(f"[File: {name}]\n```\n{extracted_text[:8000]}\n```")
            else:
                # Scanned/image-based PDF — stitch ALL pages into one composite image.
                # Sending multiple images crashes mlx_vlm's Qwen2-VL vision tower (upstream bug),
                # so we combine every page into a single tall JPEG instead.
                print(f"[PDF] '{name}' has no extractable text ({len(extracted_text)} chars). Stitching pages into composite image.")
                composite_b64 = render_pdf_as_composite(raw_bytes)
                if composite_b64:
                    has_multimodal = True
                    content_parts.append({
                        "type": "text",
                        "text": f"[File: {name}] Scanned PDF — all pages stitched into one image below (pages separated by grey lines):"
                    })
                    content_parts.append({
                        "type": "image_url",
                        "image_url": {"url": f"data:image/jpeg;base64,{composite_b64}"}
                    })

                else:
                    text_injections.append(f"[File: {name}]\n[ERROR: Could not extract text or render this PDF as images. It may be encrypted or malformed.]")
        
        else:
            # Text / code file
            extracted = extract_text_file(name, mime, raw_bytes)
            if extracted:
                text_injections.append(f"[File: {name}]\n```\n{extracted}\n```")

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
