"""
Long-Term Memory Management using Mem0 and Qdrant.

This module initializes the Mem0 memory manager with a local Qdrant instance.
Embeddings are served by LM Studio (nomic-embed-text-v1.5) to avoid loading
a separate HuggingFace model in the Python process.
"""

import os
import logging

logger = logging.getLogger(__name__)

from mem0 import Memory  # noqa: E402

config = {
    "vector_store": {
        "provider": "qdrant",
        "config": {
            "host": "localhost",
            "port": 6333,
            "collection_name": "cowork_memory_nomic",
            "embedding_model_dims": 768,
        },
    },
    "embedder": {
        "provider": "lmstudio",
        "config": {
            "model": "text-embedding-nomic-embed-text-v1.5@f16",
            "embedding_dims": 768,
            "lmstudio_base_url": "http://127.0.0.1:1234/v1",
        },
    },
}

try:
    # Mem0 implicitly initializes its internal default OpenAI client during setup,
    # so we provide a dummy key only during initialization to prevent api_key errors,
    # but we disable its automatic LLM calls below using infer=False.
    # We use setdefault so any user-provided key takes precedence.
    os.environ.setdefault("OPENAI_API_KEY", "sk-dummy-key")
    memory = Memory.from_config(config)
except Exception as e:
    logger.warning("Failed to initialize Mem0/Qdrant connection: %s", e)
    memory = None
finally:
    # Clean up the dummy key so it doesn't leak to other OpenAI SDK usage
    if os.environ.get("OPENAI_API_KEY") == "sk-dummy-key":
        os.environ.pop("OPENAI_API_KEY", None)
