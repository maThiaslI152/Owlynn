import asyncio
import os
import sys

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

async def main():
    print("Initializing agent...")
    try:
        from src.agent.graph import init_agent
        agent = await init_agent()
        print("✅ Graph initialized successfully!")
        return True
    except Exception as e:
        import traceback
        print("❌ Graph initialization failed:")
        traceback.print_exc()
        return False

if __name__ == "__main__":
    asyncio.run(main())
