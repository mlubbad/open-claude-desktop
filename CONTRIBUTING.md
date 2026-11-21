# Contributing

Thank you for testing, reporting issues, and contributing improvements!

## Prerequisites

- **Python 3.12+**
- **Node.js 22+** and `npm`
- **Rust stable** (optional, required only when building or modifying the native Tauri v2 shell in `desktop/src-tauri/`)
- **Docker** (optional, for isolated `code_execution` containers or Postgres testing)

## Quick Local Setup

```bash
# 1. Backend + CLI
python3.12 -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e "./backend[dev]"
cp .env.example .env                                    # optional: keys can also be entered in Settings UI
pre-commit install

# 2. Start the backend (loopback :8000 in dev)
uvicorn app.main:app --app-dir backend --reload

# 3. Start the React/Vite desktop UI in a second terminal (:1420 -> proxies /api to :8000)
cd desktop
npm install
npm run dev
```

To launch the full native Tauri desktop shell during development, stage stub sidecars as shown in `.github/workflows/ci.yml` (`shell` job) and run `cd desktop && npx tauri dev`.

## Running the Test & Quality Gates

All 6 CI gates must pass on every Pull Request:

```bash
pytest backend/tests                                    # 1,160+ backend unit & security tests
ruff check .                                            # Python lint
cd desktop && npm run typecheck && npm test && npm run build
```

## Pull Request Guidelines

- Open an issue first for major architectural changes; bug fixes, provider presets, MCP improvements, and docs fixes are welcome directly as PRs.
- Every bug fix or security boundary change should include a regression test.
- Never include proprietary assets, API keys, or third-party copyrighted fonts/icons.
