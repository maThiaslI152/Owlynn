#!/bin/bash
# ─── Owlynn Launcher ───────────────────────────────────────────────────────
# Starts all services, waits for readiness, launches the desktop app.
# Ctrl+C gracefully shuts everything down.

set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

BACKEND_PID=""
PODMAN_STARTED=false
LM_STUDIO_PORT=1234
BACKEND_PORT=8000

# ─── Colors ─────────────────────────────────────────────────────────────────
R='\033[0;31m'; G='\033[0;32m'; Y='\033[0;33m'; C='\033[0;36m'; NC='\033[0m'
ok()   { echo -e "  ${G}[ok]${NC} $1"; }
warn() { echo -e "  ${Y}[!!]${NC} $1"; }
fail() { echo -e "  ${R}[fail]${NC} $1"; }
info() { echo -e "  ${C}[..]${NC} $1"; }

# ─── Cleanup on exit (Ctrl+C or normal exit) ────────────────────────────────
cleanup() {
    echo ""
    echo "Shutting down..."

    # 1. Stop backend
    if [ -n "$BACKEND_PID" ] && kill -0 "$BACKEND_PID" 2>/dev/null; then
        info "Stopping backend (PID $BACKEND_PID)"
        kill "$BACKEND_PID" 2>/dev/null
        wait "$BACKEND_PID" 2>/dev/null
        ok "Backend stopped"
    fi

    # 2. Free port 8000 (in case of orphan)
    lsof -ti:$BACKEND_PORT 2>/dev/null | xargs kill -9 2>/dev/null || true

    # 3. Stop Podman containers
    if $PODMAN_STARTED; then
        info "Stopping Podman containers"
        podman compose down 2>/dev/null || podman-compose down 2>/dev/null || true
        ok "Containers stopped"
    fi

    # 4. Eject LM Studio models (free VRAM)
    info "Requesting LM Studio model unload"
    for model_id in $(curl -s http://127.0.0.1:$LM_STUDIO_PORT/v1/models 2>/dev/null | python3 -c "
import sys, json
try:
    data = json.load(sys.stdin)
    for m in data.get('data', []):
        print(m['id'])
except: pass
" 2>/dev/null); do
        curl -s -X POST "http://127.0.0.1:$LM_STUDIO_PORT/v1/models/unload" \
            -H "Content-Type: application/json" \
            -d "{\"model\": \"$model_id\"}" >/dev/null 2>&1 && \
            ok "Unloaded: $model_id" || true
    done

    echo "Done."
    exit 0
}

trap cleanup EXIT INT TERM

echo ""
echo "─── Owlynn Launcher ───"
echo ""

# ─── 1. Podman Machine ──────────────────────────────────────────────────────
info "Checking Podman..."
if ! command -v podman &>/dev/null; then
    fail "Podman is not installed. Install with: brew install podman"
    exit 1
fi

# Check if machine is running, start if not
if ! podman ps &>/dev/null; then
    info "Podman machine not responding, starting..."
    pkill -9 -f gvproxy 2>/dev/null || true
    sleep 1
    podman machine stop 2>/dev/null || true
    podman machine start 2>/dev/null || {
        warn "Podman machine start failed, trying init + start"
        podman machine init 2>/dev/null || true
        podman machine start
    }
fi
ok "Podman machine running"

# ─── 2. Containers (Redis, ChromaDB, SearXNG) ───────────────────────────────
info "Starting containers..."
if podman compose up -d 2>/dev/null || podman-compose up -d 2>/dev/null; then
    PODMAN_STARTED=true
    # Wait for containers to be ready
    info "Waiting for containers to initialize..."
    sleep 5
    ok "Containers started (Redis, ChromaDB, SearXNG)"
else
    warn "Container start failed — app will work without Redis/ChromaDB"
fi

# ─── 3. LM Studio ───────────────────────────────────────────────────────────
info "Checking LM Studio on port $LM_STUDIO_PORT..."
MAX_WAIT=30
WAITED=0
while ! curl -s "http://127.0.0.1:$LM_STUDIO_PORT/v1/models" >/dev/null 2>&1; do
    if [ $WAITED -eq 0 ]; then
        warn "LM Studio not responding. Please open LM Studio and start the server."
        echo "       Waiting up to ${MAX_WAIT}s..."
    fi
    sleep 2
    WAITED=$((WAITED + 2))
    if [ $WAITED -ge $MAX_WAIT ]; then
        fail "LM Studio not available after ${MAX_WAIT}s. Exiting."
        exit 1
    fi
done

# Show loaded models
MODELS=$(curl -s "http://127.0.0.1:$LM_STUDIO_PORT/v1/models" 2>/dev/null | python3 -c "
import sys, json
try:
    data = json.load(sys.stdin)
    models = [m['id'] for m in data.get('data', [])]
    print(', '.join(models) if models else 'none')
except: print('unknown')
" 2>/dev/null)
ok "LM Studio ready — models: $MODELS"

# ─── 4. Backend ──────────────────────────────────────────────────────────────
info "Starting backend on port $BACKEND_PORT..."

# Kill any orphan on the port
lsof -ti:$BACKEND_PORT 2>/dev/null | xargs kill -9 2>/dev/null || true
sleep 1

export PYTHONPATH="$SCRIPT_DIR:$PYTHONPATH"
export SEARXNG_URL=http://localhost:8888
source .venv/bin/activate 2>/dev/null || true

.venv/bin/python -m uvicorn src.api.server:app \
    --host 127.0.0.1 --port $BACKEND_PORT --no-access-log &
BACKEND_PID=$!

# Wait for health check
info "Waiting for backend to initialize..."
for i in $(seq 1 30); do
    if curl -s "http://127.0.0.1:$BACKEND_PORT/api/health" 2>/dev/null | grep -q '"ready"'; then
        break
    fi
    if ! kill -0 "$BACKEND_PID" 2>/dev/null; then
        fail "Backend crashed during startup."
        exit 1
    fi
    sleep 1
done

if curl -s "http://127.0.0.1:$BACKEND_PORT/api/health" 2>/dev/null | grep -q '"ready"'; then
    ok "Backend ready (PID $BACKEND_PID)"
else
    fail "Backend did not become ready in 30s."
    exit 1
fi

# ─── 5. Desktop App ─────────────────────────────────────────────────────────
echo ""
ok "All services running. Opening desktop app..."
echo "    Press Ctrl+C to shut everything down."
echo ""

export PATH="$PATH:$HOME/.cargo/bin"
npx -y @tauri-apps/cli@1 dev 2>/dev/null || {
    # If Tauri fails, just keep backend running and open browser
    warn "Tauri not available. Open http://127.0.0.1:$BACKEND_PORT in your browser."
    echo "    Press Ctrl+C to shut down."
    wait $BACKEND_PID
}
