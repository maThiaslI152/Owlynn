#!/bin/bash
# ─── Owlynn Launcher ───────────────────────────────────────────────────────
# Starts all services, waits for readiness, launches the desktop app.
# Ctrl+C gracefully shuts down the backend. Containers stay running.

set +e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

BACKEND_PID=""
LM_STUDIO_PORT=1234
BACKEND_PORT=8000

# ─── Colors ─────────────────────────────────────────────────────────────────
G='\033[0;32m'; Y='\033[0;33m'; R='\033[0;31m'; C='\033[0;36m'; NC='\033[0m'
ok()   { echo -e "  ${G}[ok]${NC} $1"; }
warn() { echo -e "  ${Y}[!!]${NC} $1"; }
fail() { echo -e "  ${R}[fail]${NC} $1"; exit 1; }
info() { echo -e "  ${C}[..]${NC} $1"; }

# ─── Cleanup on exit ────────────────────────────────────────────────────────
cleanup() {
    echo ""
    echo "Shutting down..."
    if [ -n "$BACKEND_PID" ] && kill -0 "$BACKEND_PID" 2>/dev/null; then
        info "Stopping backend (PID $BACKEND_PID)"
        kill "$BACKEND_PID" 2>/dev/null
        wait "$BACKEND_PID" 2>/dev/null || true
        ok "Backend stopped"
    fi
    lsof -ti:$BACKEND_PORT 2>/dev/null | xargs kill -9 2>/dev/null || true
    echo "Done. Containers left running for fast restart."
}
trap cleanup EXIT INT TERM

echo ""
echo "─── Owlynn Launcher ───"
echo ""

# ─── 1. Podman ───────────────────────────────────────────────────────────────
info "Checking Podman..."
if ! command -v podman &>/dev/null; then
    fail "Podman not installed. Run: brew install podman"
fi

if ! podman ps &>/dev/null; then
    info "Podman machine not responding, starting..."
    pkill -9 -f gvproxy 2>/dev/null || true
    sleep 1
    podman machine stop 2>/dev/null || true
    podman machine start 2>/dev/null || { fail "Could not start Podman machine"; }
    # Wait for socket to be ready
    for i in $(seq 1 10); do
        podman ps &>/dev/null && break
        sleep 1
    done
fi
podman ps &>/dev/null && ok "Podman machine running" || fail "Podman machine not usable"

# ─── 2. Containers ───────────────────────────────────────────────────────────
info "Checking containers..."
RUNNING=$(podman ps --format '{{.Names}}' 2>/dev/null | tr '\n' ' ')
if echo "$RUNNING" | grep -q "cowork_redis"; then
    ok "Containers already running"
else
    info "Starting containers..."
    podman compose up -d 2>/dev/null || podman-compose up -d 2>/dev/null || warn "Containers failed to start"
    info "Waiting for services to be ready..."
    sleep 8
    ok "Containers started"
fi

# Verify Redis
if curl -s telnet://localhost:6379 </dev/null &>/dev/null || podman exec cowork_redis redis-cli ping 2>/dev/null | grep -q PONG; then
    ok "Redis responding"
else
    warn "Redis not responding — will use MemorySaver fallback"
fi

# ─── 3. LM Studio ───────────────────────────────────────────────────────────
info "Checking LM Studio on port $LM_STUDIO_PORT..."
WAITED=0
while ! curl -s "http://127.0.0.1:$LM_STUDIO_PORT/v1/models" >/dev/null 2>&1; do
    if [ $WAITED -eq 0 ]; then
        warn "LM Studio not responding. Please open it and start the server."
    fi
    sleep 2
    WAITED=$((WAITED + 2))
    [ $WAITED -ge 60 ] && fail "LM Studio not available after 60s"
done

MODELS=$(curl -s "http://127.0.0.1:$LM_STUDIO_PORT/v1/models" 2>/dev/null \
    | python3 -c "import sys,json;print(', '.join(m['id'] for m in json.load(sys.stdin).get('data',[])))" 2>/dev/null || echo "unknown")
ok "LM Studio ready — $MODELS"

# ─── 4. Backend ──────────────────────────────────────────────────────────────
info "Starting backend..."
lsof -ti:$BACKEND_PORT 2>/dev/null | xargs kill -9 2>/dev/null || true
sleep 1

export PYTHONPATH="$SCRIPT_DIR:$PYTHONPATH"
export SEARXNG_URL=http://localhost:8888
source .venv/bin/activate 2>/dev/null || true

.venv/bin/python -m uvicorn src.api.server:app \
    --host 127.0.0.1 --port $BACKEND_PORT --no-access-log &
BACKEND_PID=$!

info "Waiting for backend..."
for i in $(seq 1 40); do
    if curl -s "http://127.0.0.1:$BACKEND_PORT/api/health" 2>/dev/null | grep -q '"ready"'; then
        break
    fi
    kill -0 "$BACKEND_PID" 2>/dev/null || fail "Backend crashed during startup"
    sleep 1
done
curl -s "http://127.0.0.1:$BACKEND_PORT/api/health" 2>/dev/null | grep -q '"ready"' \
    || fail "Backend not ready after 40s"
ok "Backend ready (PID $BACKEND_PID)"

# ─── 5. Desktop App ─────────────────────────────────────────────────────────
echo ""
ok "All services running"
echo "    Press Ctrl+C to shut down."
echo ""

export PATH="$PATH:$HOME/.cargo/bin"
if command -v cargo &>/dev/null; then
    npx -y @tauri-apps/cli@1 dev 2>/dev/null || {
        warn "Tauri failed. Open http://127.0.0.1:$BACKEND_PORT in your browser."
        wait $BACKEND_PID
    }
else
    warn "Rust/Cargo not found. Open http://127.0.0.1:$BACKEND_PORT in your browser."
    wait $BACKEND_PID
fi
