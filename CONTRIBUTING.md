# Contributing to Owlynn

## Development Setup

### Prerequisites

- Python 3.12+
- Node.js 18+ (for frontend tests)
- Docker/Podman (for Qdrant, SearXNG, Redis)
- LM Studio with models loaded on port 1234
- Rust & Cargo (only if building the Tauri desktop app)

### Backend Setup

```bash
# Create a virtual environment
python -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Copy environment config
cp .env.example .env
# Edit .env as needed

# Start infrastructure services
docker-compose up -d

# Run the backend
python -m uvicorn src.api.server:app --host 127.0.0.1 --port 8000 --reload
```

### Frontend Setup (v2 active)

```bash
cd frontend-v2
npm install
```

The frontend is served by the FastAPI backend at `http://127.0.0.1:8000`. For development, you can also run the Vite dev server separately:

```bash
cd frontend-v2
npm run dev
```

The Vite dev server runs on `http://127.0.0.1:5173` with API/WebSocket proxied to the backend.

### Legacy Frontend (v1 — end of life)

The old `frontend/` directory contains the original HTML/CSS/JS frontend. It is no longer actively developed.

## Code Style

### Python

- Follow PEP 8 with a 100-character line limit.
- Use Google-style docstrings for all public functions and classes.
- Type hints on function signatures (use `str | None` over `Optional[str]`).
- Imports: stdlib → third-party → local, separated by blank lines.
- Use `logging` (not `print`) for diagnostic output in production code.

### JavaScript

- Use JSDoc comments for all public functions and IIFE module APIs.
- IIFE module pattern for frontend modules (no ES module imports in browser).
- Prefer `const` over `let`; avoid `var`.
- Use `===` for comparisons.

### General

- Keep comments concise and useful — explain *why*, not *what*.
- No commented-out code in commits.
- Meaningful commit messages: `fix(router): handle empty message edge case`.

## Testing

### Backend Tests

```bash
# Run all tests
pytest tests/ -v

# Run only property-based tests
pytest tests/test_crud_properties.py -v

# Run with coverage
pytest tests/ --cov=src --cov-report=term-missing
```

- Unit tests use `unittest.TestCase`.
- Property-based tests use `hypothesis` with `@given` decorators.
- All CRUD operations must have both unit and property-based test coverage.
- Tests must clean up after themselves (delete created projects, etc.).

### Frontend Tests

```bash
cd frontend-v2
npx vitest run
```

- Component tests use `@testing-library/react` with `vitest` + `jsdom`.
- Test files go in `frontend-v2/src/components/__tests__/` with `.test.tsx` suffix.

### Before Submitting

1. All existing tests pass: `pytest tests/ -v -m "not network"` and `cd frontend-v2 && npx vitest run`
2. New features include tests.
3. No lint errors in modified files.

## PR Process

1. Create a feature branch from `main` and include the Linear issue key:
   - Format: `<issue-key>-<short-slug>`
   - Example: `WIN-7-linear-command-surface`
2. Make your changes with clear, atomic commits.
3. Ensure all tests pass locally.
4. Open a PR with a description of what changed and why.
5. Reference the Linear issue in the PR title/body:
   - Title example: `[WIN-7] Add Linear command palette skeleton`
   - Body: include `Linear: WIN-7`
6. Wait for review — at least one approval required before merge.

### Linear + GitHub linking

Owlynn uses Linear issue keys in branch names, commits, and PRs so Linear can auto-link
development work once the native GitHub integration is enabled in Linear.

Recommended commit style:
- `feat(linear): add quick issue create flow (WIN-7)`
- `fix(mcp): handle npm offline startup gracefully (WIN-6)`

Install local git warnings (once per clone):

```bash
bash scripts/install-git-hooks.sh
```

## Architecture Notes

- **Agent nodes** are pure functions `(AgentState) → AgentState` — no side effects except LLM calls and tool execution.
- **Memory scoping**: Non-default projects isolate memories via `project:<id>` user IDs in Mem0.
- **Security proxy**: All tool calls pass through `security_proxy_node` before execution. Sensitive tools require human approval via HITL interrupt.
- **Model swapping**: Only one M-tier model is loaded at a time. The `SwapManager` handles unload → load → poll via the LM Studio API.

See [docs/ARCHITECTURE_OVERVIEW.md](docs/ARCHITECTURE_OVERVIEW.md) for the full architecture reference.
