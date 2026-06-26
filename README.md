# Open Claude Desktop

A GLM-powered, Claude-Desktop-style agent workspace. It pairs a conversational
**Chainlit** chat app with a **Reflex** projects UI, and drives **Zhipu AI GLM**
models (`glm-4-plus` and the `glm-4-flash` / `glm-4.5-air` tiers) to plan, write,
and run analytics over **Google BigQuery** — with a human-in-the-loop, read-only
safety model by default.

> Formerly "AJ360 BigQuery Agent". The BigQuery tool still targets the AJ360
> (Al Jazeera 360) datasets; that domain wiring is intentional and unchanged.

## What it does

- **ReAct agent over BigQuery** — searches a schema catalog, writes standard SQL,
  dry-runs it, and (on approval) executes it, returning tables and charts.
- **Projects workspace** — per-project instructions, knowledge files, and chat
  history (Reflex UI + Chainlit data layer).
- **GLM streaming** — token streaming with `reasoning_content` ("thinking")
  rendered separately from the answer, plus incremental tool-call assembly.
- **Tools** — schema search, `run_sql`, charting, plus optional MCP servers,
  REST connectors, and sandboxed `code_execution` / `bash` / `web_fetch`.

## Architecture

| Path | Role |
|------|------|
| `app.py` | Chainlit chat app: agent loop, BigQuery client, SQL safety, charts, projects |
| `aj360_app/aj360_app/core.py` | UI-agnostic data layer (BigQuery, GLM client, Chroma) with cached singletons |
| `aj360_app/aj360_app/agent.py` | Streaming agent loop (reasoning + tool-delta handling) |
| `aj360_app/aj360_app/integrations.py` | Plugins, connectors, MCP client, sandboxed tools |
| `aj360_app/aj360_app/state.py` / `aj360_app.py` | Reflex state + pages |
| `plugins/` | Drop-in `*.py` tool modules (e.g. `calculator`) |
| `mcp_servers/` | Bundled demo MCP server |

## Security posture

- **Read-only BigQuery by default.** Non-`SELECT` statements are rejected unless
  `AJ360_ALLOW_WRITES=true`. Dataset scope is enforced on BigQuery's parsed
  `referenced_tables` (not substring matching). See `tests/test_sql_guard.py`.
- **Code execution fails shut.** `code_execution` runs only inside a container
  (`docker --network none`); with no runtime available it refuses rather than
  running on the host. `python` is not in the bash allowlist.
- **Secrets** come from Application Default Credentials (BigQuery) and `.env`
  (never a committed key file). `.gitignore` is deny-by-default for secrets, and
  runtime data (`projects/`, `.files/`, `knowledge/`, `*.csv`) is not versioned.

## Setup

```bash
python -m venv venv312 && ./venv312/Scripts/activate   # Windows
pip install -r requirements.txt
cp .env.example .env            # then fill in ZHIPU_API_KEY, auth, etc.
docker compose up -d            # local Postgres for chat history (optional)
```

Authenticate BigQuery via ADC (`gcloud auth application-default login`) or
Workload Identity — do **not** add a service-account key file to the repo.

## Run

```bash
# Chainlit chat app
chainlit run app.py            # (run.py wraps this for Python 3.14+)

# Reflex projects UI (Windows)
cd aj360_app && REFLEX_USE_NPM=true reflex run
```

## Tests

```bash
./venv312/Scripts/python.exe -m pytest tests/test_sql_guard.py
```

## Models

GLM via the `zhipuai` SDK. Configure with `AGENT_MODEL`, `VISION_MODEL`, and
`GLM_MODELS` in `.env`.
