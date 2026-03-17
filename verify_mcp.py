import asyncio
import os
import sys

# Add project root to path
sys.path.append("/Users/tim/Documents/Owlynn")

from src.tools.mcp_client import mcp_manager, get_mcp_tools
from src.config.settings import MCP_CONFIG_PATH

async def main():
    print(f"Loading config from: {MCP_CONFIG_PATH}")
    if not os.path.exists(str(MCP_CONFIG_PATH)):
         print("Config file does not exist!")
         return
         
    await mcp_manager.initialize(str(MCP_CONFIG_PATH))
    tools = get_mcp_tools()
    print(f"Loaded {len(tools)} tools:")
    for t in tools:
        print(f" - {t.name}")

if __name__ == "__main__":
    asyncio.run(main())
