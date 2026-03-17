#!/bin/bash
# Script to run MLX VLM Server

# Ensure we are in the right directory
cd "$(dirname "$0")"

echo "Starting MLX VLM Server on 127.0.0.1:8080..."
.venv/bin/python -m mlx_vlm.server --trust-remote-code --host 127.0.0.1 --port 8080