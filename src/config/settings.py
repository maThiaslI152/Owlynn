"""
Global project settings and configuration.
"""
import os
from pathlib import Path

# Base Paths
PROJECT_ROOT = Path(__file__).parent.parent.parent
DATA_DIR = PROJECT_ROOT / "data"
WORKSPACE_DIR = PROJECT_ROOT / "workspace"

# Server Settings
HOST = "0.0.0.0"
PORT = 8000

# Agent Settings
DEFAULT_MODEL = "mlx-community/Qwen2-VL-7B-Instruct-4bit"
DEFAULT_LLM_URL = "http://127.0.0.1:8080/v1"

# External Services
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
CHROMADB_HOST = os.getenv("CHROMADB_HOST", "localhost")
CHROMADB_PORT = int(os.getenv("CHROMADB_PORT", 8000))

# MCP Settings
MCP_CONFIG_PATH = PROJECT_ROOT / "mcp_config.json"

# Ensure directories exist
DATA_DIR.mkdir(parents=True, exist_ok=True)
WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)
