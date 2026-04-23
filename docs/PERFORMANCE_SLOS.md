# Performance & Memory SLOs for Local-First Operation

Target hardware: **Mac Air M4 (16 GB unified memory)**

These SLOs define the expected resource envelope for a healthy Owlynn session.
They are measured periodically and should be checked before major releases.

---

## Response Latency

| Metric | Target | Degraded | Unacceptable |
|--------|--------|----------|--------------|
| Simple query (keyword-matched) | < 2s | 2-5s | > 5s |
| Complex query (LLM-classified, medium model) | < 8s | 8-20s | > 20s |
| Streaming first token | < 3s | 3-8s | > 8s |
| Tool execution (single call) | < 5s | 5-15s | > 15s |
| WebSocket connect | < 1s | 1-3s | > 3s |

Measured from: user sends message → assistant first token received (streaming),
or final message received (non-streaming).

---

## Memory Budget

| Component | Budget | Notes |
|-----------|--------|-------|
| Python agent (langgraph + LLM pool) | 2 GB | Peak during complex reasoning + tool execution |
| Small LLM (gemma-4, loaded in LM Studio) | 1.5 GB | Always loaded |
| Medium LLM (lfm2-8b, loaded in LM Studio) | 4 GB | Loaded on demand; stays warm for session |
| Qdrant (Docker) | 512 MB | Vector store for memory |
| Redis (Docker) | 128 MB | Session state + LangGraph checkpoints |
| SearxNG (Docker) | 256 MB | Local web search |
| Frontend (Tauri + React) | 256 MB | Desktop shell + rendered UI |
| **Total sustained** | **~8.6 GB** | Medium model loaded, all services running |
| **Total peak** | **~10 GB** | During complex reasoning + web search + memory save |

**Degradation ladder when memory approaches limit (14/16 GB):**

1. Unload medium LLM from LM Studio (fall back to small LLM only)
2. Reduce context window to 50K tokens
3. Disable auto-summarize (keep full context at reduced window)
4. If below 1 GB free, terminate SearxNG container

---

## Storage

| Resource | Budget | Notes |
|----------|--------|-------|
| Codebase + build artifacts | ~500 MB | Python venv, node_modules, dist |
| Qdrant vectors | ~200 MB | Per ~50K memory entries |
| Redis RDB snapshots | ~100 MB | Session checkpoints |
| Audit logs | ~50 MB | JSONL audit bundles |
| **Total** | **~850 MB** | |

---

## CPU / Thermal

| Metric | Target | Degraded | Unacceptable |
|--------|--------|----------|--------------|
| Idle CPU (no active query) | < 10% | 10-30% | > 30% |
| Query CPU (streaming response) | < 80% | 80-95% | > 95% sustained |
| Fan noise during normal use | silent | audible | loud |
| Thermal throttle events | 0 per session | 1-2 per session | > 2 per session |

---

## Throughput

| Metric | Target |
|--------|--------|
| Concurrent sessions | 1 (active) + unlimited (idle, checkpointed) |
| Streaming tokens/second (medium model) | > 30 tok/s |
| Streaming tokens/second (small model) | > 80 tok/s |
| WebSocket reconnect | < 2s |
| Project switch latency | < 500ms |

---

## Availability

| Metric | Target |
|--------|--------|
| Services uptime (Qdrant, Redis, SearxNG) | 99.9% per session |
| Non-graceful degradation rate | < 1% of queries |
| Graph execution error rate | < 0.5% of queries |
| WS disconnect rate | < 1 per 100 queries |

---

## Measuring SLOs

### Quick check (before commit)

```bash
# Python agent memory
ps -o rss,pid -p $(pgrep -f "python.*uvicorn" | head -1)

# LM Studio memory (the bulk of usage)
ps -o rss,pid -p $(pgrep -f "LM Studio" | head -1) 2>/dev/null || echo "LM Studio not running"

# Docker containers
docker stats --no-stream qdrant redis searxng 2>/dev/null

# Frontend bundle size
ls -lh frontend-v2/dist/assets/index-*.js frontend-v2/dist/assets/index-*.css
```

### Full SLO check (pre-release)

```bash
# Run the audit-verify CI gate
cd frontend-v2 && npm run build
cd .. && python3 -m pytest tests/test_websocket_event_contract.py tests/test_verify_report_fixture.py tests/test_frontend_cutover_serving.py --tb=short

# Manual latency check (requires LM Studio + containers running)
time python3 -c "
import asyncio
from src.agent.llm import get_small_llm
loop = asyncio.get_event_loop()
llm = loop.run_until_complete(get_small_llm())
result = loop.run_until_complete(llm.ainvoke(['hello']))
print(result.content[:100])
"
```

---

## Policy

1. **Memory budget is hard** — if the sum of all services exceeds 14 GB (2 GB headroom),
   reduce model size or disable features before releasing.
2. **Latency regressions > 20%** require investigation and documentation before proceeding
   to the next development phase.
3. **Thermal throttling during normal use** (non-query idle) is a blocker — fix before
   next release.
4. **SLOs are checked manually before phase transitions** (no automated SLO gate yet).
