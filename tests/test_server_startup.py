import asyncio
import sys
from unittest.mock import MagicMock

# Mock mem0 and redis IF needed, but ideally we want to see if our basic imports work.
# Let's import the app and trigger lifespan to see if it blows up on graph initialization.

sys.path.append("/Users/tim/Documents/Owlynn")

async def main():
    try:
        from src.api.server import app
        # Trigger lifespan
        async with app.router.lifespan_context(app):
             print("Server lifespan initialized successfully")
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"Server Startup Failed: {e}")

if __name__ == "__main__":
    asyncio.run(main())
