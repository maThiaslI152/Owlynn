#!/bin/bash
# One-Stop Launch Script for Owlynn Desktop App

echo "🚀 Starting Owlynn Desktop App Prep..."

# Ensure we're in the right directory
cd "$(dirname "$0")"

# 1. Start Support Services (Redis + Chroma) via Podman
echo "-> Checking support services (Redis + ChromaDB)..."
if command -v podman > /dev/null 2>&1; then
    # Try using 'podman compose' or fallback to 'podman-compose'
    if podman compose up -d || podman-compose up -d; then
        echo "✅ Support services started."
    else
        echo "❌ Failed to start Podman containers."
        echo ""
        echo "💡 It looks like you are missing a compose provider (podman-compose / docker-compose)."
        echo "👉 Fix it by running this in your terminal:"
        echo "   brew install podman-compose"
        echo ""
        echo "Alternatively, you can install via pip: pip install podman-compose"
        exit 1
    fi

else
    echo "❌ Error: Podman is not installed."
    exit 1
fi


# 2. Check LM Studio Connection
echo "-> Verifying LM Studio local server..."
if ! curl -s http://127.0.0.1:1234/v1/models > /dev/null; then
    echo "⚠️  LM Studio is NOT responding on http://127.0.0.1:1234"
    echo "👉 Please:"
    echo "   1. Open LM Studio"
    echo "   2. Load your model (e.g., Qwen3.5)"
    echo "   3. Enable the 'Local Inference Server' on port 1234"
    echo ""
    read -p "Press [Enter] after starting LM Studio to continue, or Ctrl+C to abort..."
fi

# Double check
if ! curl -s http://127.0.0.1:1234/v1/models > /dev/null; then
    echo "❌ Connect failed again. Exiting."
    exit 1
fi
echo "✅ LM Studio verified."

# 3. Start FastAPI Backend in background
echo "-> Starting Backend..."
export PYTHONPATH=$PYTHONPATH:$(pwd)
export SEARXNG_URL=http://localhost:8888
source .venv/bin/activate

# Be robust: kill any old instance listening on 8000
# (Since lsof might require permissions, we try to start uvicorn safely)
.venv/bin/python -m uvicorn src.api.server:app --host 127.0.0.1 --port 8000 --reload &
BACKEND_PID=$!

echo "Backend PID: $BACKEND_PID"
echo "Backend PID: $BACKEND_PID"
echo "Waiting for Backend to fully initialize..."

# Active wait loop for server and agent readiness
while true; do
    RESPONSE=$(curl -s http://127.0.0.1:8000/api/health)
    if [[ "$RESPONSE" == *"\"agent\":\"ready\""* ]]; then
        break
    fi
    sleep 1
    # Fail fast if backend process died
    if ! kill -0 $BACKEND_PID 2>/dev/null; then
        echo "❌ Backend crashed during startup."
        exit 1
    fi
done


echo "✅ Backend fully started."


# 4. Start Tauri App
echo "-> Starting Tauri Desktop App..."
export PATH=$PATH:$HOME/.cargo/bin

# Dev will open window & rebuild if files change
npx -y @tauri-apps/cli@1 dev

# 5. Cleanup on Exit
echo "-> Stopping Backend (PID $BACKEND_PID)..."
kill $BACKEND_PID
echo "Done."
