#!/bin/bash
# Owlynn Launcher — simple and reliable
cd "$(dirname "$0")"

echo ""
echo "── Owlynn ──"
echo ""

# 1. Podman containers
echo "[1/4] Containers..."
# Run podman check in background with hard 15s timeout to avoid hanging
(
    _running=false
    podman ps 2>/dev/null | grep -q cowork_chromadb && podman ps 2>/dev/null | grep -q cowork_redis && _running=true
    if $_running; then
        echo "      Already running."
    else
        echo "      Starting containers..."
        podman machine start 2>/dev/null
        podman compose up -d 2>/dev/null || podman-compose up -d 2>/dev/null
        echo "      Waiting 8s for services..."
        sleep 8
    fi
) &
_container_pid=$!
(sleep 15 && kill $_container_pid 2>/dev/null) &
_timer_pid=$!
wait $_container_pid 2>/dev/null
kill $_timer_pid 2>/dev/null
wait $_timer_pid 2>/dev/null
echo "      Done."

# Check Podman machine memory
_podman_mem=$(podman machine inspect 2>/dev/null | grep -o '"Memory":[0-9]*' | grep -o '[0-9]*' || echo "0")
if [ "$_podman_mem" -gt 0 ] && [ "$_podman_mem" -lt 2048 ]; then
    echo "      ⚠️  Podman machine memory is low ($_podman_mem MB). Recommend: podman machine set --memory 4096"
fi

# 2. LM Studio
echo "[2/4] LM Studio..."
if curl -s http://127.0.0.1:1234/v1/models >/dev/null 2>&1; then
    echo "      Ready."
else
    echo "      Not responding on port 1234."
    echo "      Please open LM Studio and start the server."
    read -p "      Press Enter when ready..."
    curl -s http://127.0.0.1:1234/v1/models >/dev/null 2>&1 || { echo "      Still not available. Exiting."; exit 1; }
fi

# 3. Backend
echo "[3/4] Backend..."
lsof -ti:8000 2>/dev/null | xargs kill -9 2>/dev/null
sleep 1

export PYTHONPATH="$(pwd):$PYTHONPATH"
export SEARXNG_URL=http://localhost:8888
source .venv/bin/activate 2>/dev/null

.venv/bin/python -m uvicorn src.api.server:app --host 127.0.0.1 --port 8000 --no-access-log &
PID=$!

for i in $(seq 1 30); do
    curl -s http://127.0.0.1:8000/api/health 2>/dev/null | grep -q ready && break
    sleep 1
done
echo "      Ready (PID $PID)."

# 4. Desktop app
echo "[4/4] Opening app..."
echo ""
echo "      Press Ctrl+C to stop."
echo ""

export PATH="$PATH:$HOME/.cargo/bin"
npx -y @tauri-apps/cli@1 dev 2>/dev/null || {
    echo "      Tauri not available. Open http://127.0.0.1:8000"
    wait $PID
}

# Cleanup
echo ""
echo "Stopping backend..."
kill $PID 2>/dev/null
wait $PID 2>/dev/null
echo "Done."
