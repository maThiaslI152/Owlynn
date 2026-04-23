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


def normalize_project_id(project_id: str | None) -> str:
    if project_id is None:
        return "default"
    s = str(project_id).strip()
    if not s or s.lower() in ("null", "undefined"):
        return "default"
    return s


def get_project_workspace(project_id: str | None = None) -> str:
    """Absolute path for project-scoped files (matches REST/WS uploads under workspace/projects/<id>)."""
    pid = normalize_project_id(project_id)
    path = WORKSPACE_DIR / "projects" / pid
    path.mkdir(parents=True, exist_ok=True)
    return str(path.resolve())

# Server Settings
HOST = os.getenv("HOST", "127.0.0.1")
PORT = int(os.getenv("PORT", "8000"))

# External Services
QDRANT_HOST = os.getenv("QDRANT_HOST", "localhost")
QDRANT_PORT = int(os.getenv("QDRANT_PORT", 6333))

# MCP Settings
MCP_CONFIG_PATH = PROJECT_ROOT / "mcp_config.json"

# Web RAG (fetch_webpage excerpt ranking; optional web_search snippet rerank)
WEB_RAG_ENABLED = os.getenv("WEB_RAG_ENABLED", "true").strip().lower() in {"1", "true", "yes", "on"}
WEB_RAG_EMBED_MODEL = os.getenv("WEB_RAG_EMBED_MODEL", "text-embedding-nomic-embed-text-v1.5@f16")
WEB_RAG_TOP_K = int(os.getenv("WEB_RAG_TOP_K", "5"))
WEB_RAG_CHUNK_CHARS = int(os.getenv("WEB_RAG_CHUNK_CHARS", "720"))
WEB_RAG_CHUNK_OVERLAP = int(os.getenv("WEB_RAG_CHUNK_OVERLAP", "120"))
# Run embedding rank when plain text is at least this many characters
WEB_RAG_MIN_CHARS_FOR_RANK = int(os.getenv("WEB_RAG_MIN_CHARS_FOR_RANK", "1800"))
WEB_SEARCH_RERANK_TOP_N = int(os.getenv("WEB_SEARCH_RERANK_TOP_N", "8"))

# Web search reliability controls
# Provider routing: auto | brave | serper | tavily | none
WEB_SEARCH_PROVIDER = (os.getenv("WEB_SEARCH_PROVIDER", "auto") or "auto").strip().lower()
WEB_SEARCH_TIMEOUT_SECONDS = float(os.getenv("WEB_SEARCH_TIMEOUT_SECONDS", "22"))
WEB_SEARCH_ENABLE_CURL_CFFI = os.getenv("WEB_SEARCH_ENABLE_CURL_CFFI", "true").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}
WEB_SEARCH_ENABLE_BROWSER_FALLBACK = os.getenv(
    "WEB_SEARCH_ENABLE_BROWSER_FALLBACK", "true"
).strip().lower() in {"1", "true", "yes", "on"}

# Tier-1 provider keys (optional)
BRAVE_SEARCH_API_KEY = (os.getenv("BRAVE_SEARCH_API_KEY", "") or "").strip()
SERPER_API_KEY = (os.getenv("SERPER_API_KEY", "") or "").strip()
TAVILY_API_KEY = (os.getenv("TAVILY_API_KEY", "") or "").strip()

# SearXNG (self-hosted metasearch — recommended for local setups, no API keys / no bot blocking)
SEARXNG_URL = (os.getenv("SEARXNG_URL", "") or "").strip()  # e.g. "http://localhost:8888"

# ─── Redis & DeepSeek ──────────────────────────────────────────────────────
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
DEEPSEEK_API_KEY = (os.getenv("DEEPSEEK_API_KEY", "") or "").strip()

# Context windows per model tier
MEDIUM_DEFAULT_CONTEXT = 100000
MEDIUM_LONGCTX_CONTEXT = int(os.getenv("MEDIUM_LONGCTX_CONTEXT", "131072"))
CLOUD_CONTEXT = 131072

# ─── M4 MAC AIR OPTIMIZATION ───────────────────────────────────────────────
# These settings are optimized for Mac M4 Air with small-large model architecture
# Adjust based on your specific machine configuration

M4_MAC_OPTIMIZATION = {
    "small_model": {
        "max_tokens": 512,       # Routing doesn't need long responses
        "context_length": 4096,  # Lfm2.5 1.2B context window
        "temperature": 0.1,      # Lower for consistent routing
        "timeout": 10,           # seconds - small model should be fast
    },
    "large_model": {
        "max_tokens": 8192,       # Dynamic budget handles this per-request
        "context_length": 100000, # Qwen3.5 9B context window (set in LM Studio)
        "temperature": 0.5,
        "timeout": 120,          # seconds - longer timeout for big context
        "cloud_timeout": 180,    # seconds - accommodate cloud API latency
    },
    "medium_models": {
        "swap_timeout": 120,     # seconds - max wait for LM Studio model swap
        "poll_interval": 2,      # seconds - poll interval during swap
    },
    "memory": {
        "max_facts": 150,        # Reduced from 200 for M4 memory
        "search_window": 50,     # Only search recent 50 memories (not all 150)
        "cache_ttl": 300,        # Cache memory context for 5 minutes
        "cache_cleanup": 600,    # Clean old cache entries every 10 min
    },
    "checkpoint": {
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
