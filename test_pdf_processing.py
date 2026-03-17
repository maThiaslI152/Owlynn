import asyncio
import os
import sys
import base64

sys.path.append("/Users/tim/Documents/Owlynn")

from src.agent.graph import init_agent
from src.api.server import build_message_content
from langchain_core.messages import HumanMessage

async def main():
    # 1. Create a dummy PDF
    try:
        import fitz
        doc = fitz.open()
        page = doc.new_page()
        page.insert_text((50, 50), "This is a test PDF document for agent reasoning. It has some text content to see if the agent can parse it and answer correctly.")
        pdf_bytes = doc.write()
        doc.close()
    except Exception as e:
        print(f"Failed to create PDF using fitz: {e}")
        return

    # Base64 encode
    pdf_b64 = base64.b64encode(pdf_bytes).decode()

    # 2. Build message content
    files = [{
        "name": "test_document.pdf",
        "type": "application/pdf",
        "data": pdf_b64
    }]
    content = build_message_content("Please summarize the content in this PDF.", files)
    print(f"Built Message Content type: {type(content)}")
    print(f"Content parts: {content if isinstance(content, str) else len(content)} items")

    # 3. Initialize Agent
    agent = await init_agent()

    # 4. Stream events to trace node traversal
    input_data = {
        "messages": [HumanMessage(content=content)],
        "mode": "tools_on",
        "project_id": "default"
    }
    config = {"configurable": {"thread_id": "test_thread_pdf"}}

    print("\n--- Starting Graph Execution Trace ---")
    try:
        async for event in agent.astream_events(input_data, config=config, version="v2"):
            kind = event.get("event")
            metadata = event.get("metadata", {})
            node = metadata.get("langgraph_node")
            
            if kind == "on_chain_start" and node:
                print(f"➡️ Enter Node: {node}")
            elif kind == "on_chain_end" and node:
                print(f"⬅️ Exit Node: {node}")
            elif kind == "on_chat_model_stream":
                pass # suppress stream chunks for clarity
    except Exception as e:
        print(f"\n💥 Graph Execution Error: {e}")
    print("--- Graph Execution Finished ---")

if __name__ == "__main__":
    asyncio.run(main())
