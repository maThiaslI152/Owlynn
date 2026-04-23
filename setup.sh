#!/bin/bash
set -e

# Setup Script for Local Cowork Agent
echo "Starting local environment setup..."

# 1. Start support services manually via podman run
echo "Starting Podman services (ChromaDB)..."

# Stop existing if they exist
podman stop cowork_chromadb 2>/dev/null || true
podman rm cowork_chromadb 2>/dev/null || true

# Start ChromaDB
echo "Starting ChromaDB..."
podman run -d --name cowork_chromadb -p 8000:8000 -v cowork_chroma_data:/chroma/chroma chromadb/chroma:latest

# Podman machine memory configuration (4GB for containers)
echo "Configuring Podman machine memory..."
echo "  Note: If creating a new machine, use: podman machine init --memory 4096"
echo "  For existing machines: podman machine set --memory 4096"

# Start Redis
echo "Starting Redis..."
podman stop cowork_redis 2>/dev/null || true
podman rm cowork_redis 2>/dev/null || true
podman run -d --name cowork_redis -p 6379:6379 -v cowork_redis_data:/data redis:7-alpine redis-server --appendonly yes

# Verify Redis connectivity
echo "Verifying Redis..."
for i in $(seq 1 10); do
    if podman exec cowork_redis redis-cli ping 2>/dev/null | grep -q PONG; then
        echo "  Redis is ready."
        break
    fi
    sleep 1
done

# 2. Recreate virtual environment using a stable python (3.11 preferred if available)
echo "Recreating Python virtual environment..."
rm -rf .venv

if command -v python3.11 &>/dev/null; then
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

echo "Setup complete! You can now run the agent."
