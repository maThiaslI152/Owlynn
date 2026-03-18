#!/bin/bash
# Script to launch full Backend + Tauri Desktop App together

echo "Starting Owlynn Desktop App Environment..."

# Ensure we're in the right directory
cd /Users/tim/Documents/Owlynn

# 1. Start FastAPI Backend in background
echo "-> Starting FastAPI Backend in background..."
export PYTHONPATH=$PYTHONPATH:$(pwd)
source .venv/bin/activate

# Run Uvicorn in background
uvicorn src.api.server:app --host 127.0.0.1 --port 8000 --reload &
BACKEND_PID=$!

echo "Backend PID: $BACKEND_PID"
echo "Waiting for Backend to start..."
sleep 3 # Give it a moment to bind to port 8000

# 2. Start Tauri Desktop App
echo "-> Checking Tauri Icons..."
if [ ! -f src-tauri/icons/128x128.png ]; then
    echo "-> Generating Tauri Icons from icon.png..."
    export PATH=$PATH:$HOME/.cargo/bin
    npx -y @tauri-apps/cli@1 icon /Users/tim/Documents/Owlynn/icon.png
fi

echo "-> Starting Tauri Desktop App..."
# Ensure Rust cargo is in PATH if recently installed via script
export PATH=$PATH:$HOME/.cargo/bin

# Dev will open window & rebuild if files change
npx -y @tauri-apps/cli@1 dev





# 3. Cleanup on Exit
echo "-> Stopping Backend (PID $BACKEND_PID)..."
kill $BACKEND_PID
echo "Done."
