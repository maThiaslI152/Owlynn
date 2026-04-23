"""
MCP Client Manager for LangChain.

This module provides the `MCPClientManager` to consume Model Context Protocol (MCP)
servers as native LangChain tools by establishing STDIO transports.
"""

import asyncio
import json
import os
import logging
from typing import List, Dict, Any, Optional
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from langchain_core.tools import BaseTool, Tool
from pydantic import Field

logger = logging.getLogger(__name__)

class MCPTool(BaseTool):
    """
    A LangChain tool that delegates execution to an MCP server.
    """
    name: str
    description: str
    server_name: str
    mcp_tool_name: str
    manager: 'MCPClientManager' = Field(exclude=True)

    async def _arun(self, **kwargs) -> str:
        return await self.manager.execute_tool(self.server_name, self.mcp_tool_name, kwargs)

    def _run(self, **kwargs) -> str:
        # Since we are in an async-first environment, we should ideally use _arun.
        # But if sync is required, we run the event loop.
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        
        if loop.is_running():
            # This is tricky if already in an event loop. 
            # In LangGraph async nodes, _arun will be called.
            return "Error: Use async _arun"
        
        return loop.run_until_complete(self._arun(**kwargs))

class MCPClientManager:
    """
    Manages connections to external MCP servers to ingest them as LangChain tools.
    """
    
    def __init__(self):
        self.sessions: Dict[str, ClientSession] = {}
        self.langchain_tools: List[BaseTool] = []
        self._server_params: Dict[str, StdioServerParameters] = {}
        self._initialized = False

    async def initialize(self, config_path: str = "mcp_config.json"):
        if self._initialized:
            return
            
        if not os.path.exists(config_path):
            logger.info("No MCP config found at %s. Skipping external tools.", config_path)
            self._initialized = True
            return

        try:
            with open(config_path, "r") as f:
                config = json.load(f)
        except Exception as e:
            logger.warning("Failed to load MCP config: %s", e)
            self._initialized = True
            return
            
        mcp_servers = config.get("mcpServers", {})
        
        for name, details in mcp_servers.items():
            command = details.get("command")
            args = details.get("args", [])
            env = details.get("env")
            
            if not command:
                continue
                
            params = StdioServerParameters(command=command, args=args, env=env)
            self._server_params[name] = params
            
            try:
                # We establish a session to discover tools
                async with stdio_client(params) as (read, write):
                    async with ClientSession(read, write) as session:
                        await session.initialize()
                        tools_response = await session.list_tools()
                        
                        for mcp_tool in tools_response.tools:
                            lc_tool = MCPTool(
                                name=f"{name}_{mcp_tool.name}",
                                description=mcp_tool.description or f"Tool {mcp_tool.name} from {name} server",
                                server_name=name,
                                mcp_tool_name=mcp_tool.name,
                                manager=self,
                                args_schema=None # We could dynamically build this from inputSchema
                            )
                            self.langchain_tools.append(lc_tool)
                            logger.info("Loaded MCP tool: %s", lc_tool.name)
            except Exception as e:
                logger.warning("Failed to connect to MCP server %s: %s", name, e)

        self._initialized = True

    async def execute_tool(self, server_name: str, tool_name: str, arguments: dict) -> str:
        params = self._server_params.get(server_name)
        if not params:
            return f"Error: MCP server {server_name} not configured."
            
        try:
            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    result = await session.call_tool(tool_name, arguments)
                    
                    # MCP results can have multiple content items
                    text_parts = [item.text for item in result.content if hasattr(item, 'text')]
                    return "\n".join(text_parts)
        except Exception as e:
            return f"Error executing MCP tool {tool_name} on {server_name}: {str(e)}"

    def get_tools(self) -> List[BaseTool]:
        return self.langchain_tools

# Global manager instance
mcp_manager = MCPClientManager()

def get_mcp_tools() -> List[BaseTool]:
    """
    Returns the list of dynamically ingested LangChain tools originating from MCP servers.
    Note: Requires mcp_manager.initialize() to have been called.
    """
    return mcp_manager.get_tools()
