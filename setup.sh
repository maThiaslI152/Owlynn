#!/bin/bash
set -e

# Setup Script for Local Cowork Agent
echo "Starting local environment setup..."

# 1. Start support services manually via podman run
echo "Starting Podman services (Redis, ChromaDB)..."

# Stop existing if they exist
podman stop cowork_redis cowork_chromadb 2>/dev/null || true
podman rm cowork_redis cowork_chromadb 2>/dev/null || true

# Start Redis
echo "Starting Redis..."
podman run -d --name cowork_redis -p 6379:6379 -v cowork_redis_data:/data redis:alpine

# Start ChromaDB
echo "Starting ChromaDB..."
podman run -d --name cowork_chromadb -p 8000:8000 -v cowork_chroma_data:/chroma/chroma chromadb/chroma:latest

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
