"""
Long-Term Memory Management using Mem0 and ChromaDB.

This module initializes the Mem0 memory manager with a local ChromaDB instance.
The `memory` singleton is used by memory nodes and tools for semantic search/storage.
"""

import os
import logging

logger = logging.getLogger(__name__)

# Mem0 implicitly initializes its internal default OpenAI client during setup,
# so we provide a dummy key to prevent `api_key` initialization errors,
# but we disable its automatic LLM calls below using `infer=False`.
os.environ["OPENAI_API_KEY"] = "sk-dummy-key"

from mem0 import Memory

# Initialize Mem0 to use the local ChromaDB Podman instance
config = {
    "vector_store": {
        "provider": "chroma",
        "config": {
            "host": "localhost",
            "port": 8100,
            "collection_name": "cowork_memory_mE5",
        },
    },
    "embedder": {
        "provider": "huggingface",
        "config": {
            "model": "intfloat/multilingual-e5-small",
        },
    },
}

try:
    memory = Memory.from_config(config)
except Exception as e:
    logger.warning(f"Failed to initialize Mem0/ChromaDB connection: {e}")
    memory = None
