"""
Global project settings and configuration.
Includes M4 Mac Air optimization settings.
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

# ─── M4 MAC AIR OPTIMIZATION ───────────────────────────────────────────────
# These settings are optimized for Mac M4 Air with small-large model architecture
# Adjust based on your specific machine configuration

M4_MAC_OPTIMIZATION = {
    "small_model": {
        "max_tokens": 1024,      # Routing doesn't need long responses
        "temperature": 0.3,      # Lower for consistent routing
        "timeout": 10,           # seconds - small model should be fast
    },
    "large_model": {
        "max_tokens": 4096,      # Reduced from 8192 for M4 memory efficiency
        "temperature": 0.4,
        "timeout": 30,           # seconds - allow time for reasoning
    },
    "memory": {
        "max_facts": 150,        # Reduced from 200 for M4 memory
        "search_window": 50,     # Only search recent 50 memories (not all 150)
        "cache_ttl": 300,        # Cache memory context for 5 minutes
        "cache_cleanup": 600,    # Clean old cache entries every 10 min
    },
    "checkpoint": {
        "use_redis": False,      # MemorySaver for M4 (no Redis overhead)
        "memory_cleanup_interval": 3600,  # Clean old threads hourly
    },
    "routing": {
        "keyword_bypass": True,  # Quick routing for common patterns
        "simple_prompt": True,   # Use streamlined prompt for speed
    },
    "threading": {
        "max_workers": 2,        # M4 has 8 cores, use 2 to avoid contention
        "queue_size": 10,        # Limit concurrent requests
    }
}

# Apply M4 optimization if specified
if os.getenv("MACHINE_TYPE") == "M4_MAC" or os.getenv("OPTIMIZE_FOR_M4", "").lower() == "true":
    MODEL_TIMEOUT_SMALL = M4_MAC_OPTIMIZATION["small_model"]["timeout"]
    MODEL_TIMEOUT_LARGE = M4_MAC_OPTIMIZATION["large_model"]["timeout"]
    MAX_TOKENS_SMALL = M4_MAC_OPTIMIZATION["small_model"]["max_tokens"]
    MAX_TOKENS_LARGE = M4_MAC_OPTIMIZATION["large_model"]["max_tokens"]
    MAX_MEMORIES = M4_MAC_OPTIMIZATION["memory"]["max_facts"]
    MEMORY_SEARCH_WINDOW = M4_MAC_OPTIMIZATION["memory"]["search_window"]
else:
    # Standard defaults (non-M4)
    MODEL_TIMEOUT_SMALL = 15
    MODEL_TIMEOUT_LARGE = 45
    MAX_TOKENS_SMALL = 1024
    MAX_TOKENS_LARGE = 8192
    MAX_MEMORIES = 200
    MEMORY_SEARCH_WINDOW = 200

# Ensure directories exist
DATA_DIR.mkdir(parents=True, exist_ok=True)
WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)
