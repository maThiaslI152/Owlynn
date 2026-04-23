#!/bin/bash
set -e

# Setup Script for Local Cowork Agent
echo "Starting local environment setup..."

# 1. Start support services manually via podman run
echo "Starting Podman services..."

# --- Qdrant (vector database for long-term memory) ---
echo "Starting Qdrant..."
podman stop cowork_qdrant 2>/dev/null || true
podman rm cowork_qdrant 2>/dev/null || true
podman run -d --name cowork_qdrant \
  -p 6333:6333 -p 6334:6334 \
  -v cowork_qdrant_data:/qdrant/storage \
  qdrant/qdrant:latest

# --- Redis (session checkpointing) ---
echo "Starting Redis..."
podman stop cowork_redis 2>/dev/null || true
podman rm cowork_redis 2>/dev/null || true
podman run -d --name cowork_redis \
  -p 6379:6379 \
  -v cowork_redis_data:/data \
  redis:7-alpine redis-server --appendonly yes

# Verify Redis connectivity
echo "Verifying Redis..."
for i in $(seq 1 10); do
    if podman exec cowork_redis redis-cli ping 2>/dev/null | grep -q PONG; then
        echo "  Redis is ready."
        break
    fi
    sleep 1
done

# --- Optional: SearXNG (self-hosted metasearch, no API keys needed) ---
if [ "${SKIP_SEARXNG:-0}" != "1" ]; then
    echo "Starting SearXNG..."
    podman stop cowork_searxng 2>/dev/null || true
    podman rm cowork_searxng 2>/dev/null || true
    podman run -d --name cowork_searxng \
      -p 8888:8080 \
      -v cowork_searxng_data:/etc/searxng \
      searxng/searxng:latest
fi

# Podman machine memory configuration (minimum 4GB for containers)
echo "Configuring Podman machine memory..."
echo "  Note: If creating a new machine, use: podman machine init --memory 4096"
echo "  For existing machines: podman machine set --memory 4096"

# 2. Recreate virtual environment
echo "Recreating Python virtual environment..."
rm -rf .venv

if command -v python3.12 &>/dev/null; then
  echo "Using python3.12"
  python3.12 -m venv .venv
elif command -v python3.11 &>/dev/null; then
  echo "Using python3.11"
  python3.11 -m venv .venv
else
  echo "Using default python3"
  python3 -m venv .venv
fi

# 3. Activate and install dependencies
echo "Installing Python dependencies..."
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
pip install -r requirements-dev.txt

echo ""
echo "Setup complete! Next steps:"
echo "  1. Copy .env.example to .env and configure as needed"
echo "  2. Start LM Studio and load your models"
echo "  3. Run ./start.sh to launch the agent"
echo ""
