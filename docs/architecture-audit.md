# Architecture Audit — Open Claude Desktop

> **Date:** 2026-06-26 · **Scope:** project structure + ops/quality/governance.
> **Method:** `git ls-files` + `stat` recon, multi-agent structural audit
> (every issue verified against the real tree), then a hygiene/ops pass.
> Saved here (versioned `docs/`) rather than `knowledge/` because the app
> ingests `knowledge/**/*.md` into the BigQuery agent's RAG (`rglob("*.md")`),
> so an audit there would pollute agent answers.

## Project

* **Tech:** Python 3.12 · Chainlit (`app.py`) · Reflex 0.9.5 (`aj360_app/`) ·
  Zhipu GLM (`zhipuai`) · Google BigQuery · ChromaDB + Kùzu · Postgres · MCP.
* **Description:** A GLM-powered, Claude-Desktop-style agent that runs read-only
  BigQuery analytics, with a Chainlit chat surface and a parallel Reflex
  projects/workspace surface sharing on-disk state.

## Issue summary

| # | Severity | Category | Issue |
|---|----------|----------|-------|
| 1 | 🔴 High | Structure | Chainlit `.chainlit/` scaffold duplicated into the Reflex app (24 dead files) |
| 2 | 🔴 High | Structure | Stray root `config.toml` shadows & has drifted from `.chainlit/config.toml` |
| 3 | 🔴 High | Architecture | `app.py` god module (2,786 lines) + Chainlit/Reflex duplicate domain logic |
| 4 | 🟡 Med | Packaging | Two `requirements.txt`, no `pyproject.toml`, root is a raw pip-freeze |
| 5 | 🟡 Med | Testing | No installable package → tests load code via `importlib.spec_from_file_location` |
| 6 | 🟡 Med | Env | Two virtualenvs + machine-absolute path pinned in `mcp_servers.json` |
| 7 | 🟡 Med | Structure | Overloaded repo root: runtime/data dirs + loose notes at top level |
| 8 | 🟡 Med | Naming | "Open Claude Desktop" vs `aj360*` artifacts; triple-nested module |
| 9 | 🟢 Low | Hygiene | Committed scratch artifacts + 301 KB generated lockfile |
| 10 | 🔴 High | CI/CD | No CI pipeline (no `.github/workflows/`) — tests & guards never run automatically |
| 11 | 🟡 Med | Quality | No linter/formatter/type-checker/pre-commit config (no quality gate) |
| 12 | 🔴 High | Security | No pre-commit **secret scan** despite a prior credential leak |
| 13 | 🟡 Med | Governance | No `LICENSE`, `SECURITY.md`, `CONTRIBUTING.md`, or `CODEOWNERS` |
| 14 | 🟡 Med | Deploy | No `Dockerfile`/`.dockerignore`; compose runs only Postgres, not the apps |
| 15 | 🟡 Med | Testing | Low coverage: 3 test files for 17 source modules; critical paths untested |
| 16 | 🟢 Low | Hygiene | `aj360-daily-insights.skill` is a committed ZIP binary at repo root |
| 17 | 🟢 Low | Ops | File-based audit log (`logs/agent_audit.jsonl`) with no rotation |

---

## Resolution status (2026-06-26)

**Resolved & pushed** (commits `7515411` → `0868947`): **#1, #2, #4, #6, #8, #9,
#10, #11, #12, #14, #15, #16, #17** — each verified (compile + tests green; the
MCP placeholder fix and the auth gate were exercised end-to-end).

**Deferred, with reason:**
- **#3 god module + shared core** — a multi-file refactor of two *working* apps;
  too risky to one-shot. Needs a dedicated, planned effort (extract `ocd_core/`,
  then split `app.py`). Duplication was reduced opportunistically (the read-only
  SQL guard is correct in both apps).
- **#5 tests via real imports** — pytest config is in place (#11); converting the
  `spec_from_file_location` loaders to plain imports is coupled to #3's package
  restructure (flat `app.py` + nested `aj360_app/aj360_app`). The loaders work and
  isolate `app.py`'s heavy import side effects.
- **#7 runtime data layout** — moving `chroma_db/`, `projects/`, etc. under a
  `runtime/` dir touches many path constants in both apps + live-data migration
  (risky), and those dirs are already git-ignored (the repo is not polluted).
- **#13 LICENSE** — intentionally not chosen on your behalf (an ownership/legal
  decision). The rest of #13 (SECURITY.md, CONTRIBUTING.md, CODEOWNERS) is done.

**Your action still required:** rotate the leaked SA key + `.env` secrets in GCP/Z.ai.

## Round 1 — Structure (verified)

### 🔴 1. Chainlit scaffold duplicated into the Reflex app (24 dead files)
Reflex never reads `.chainlit/`, yet the whole Chainlit config+i18n set is cloned and committed inside the Reflex app.
* **Affected:** `aj360_app/.chainlit/config.toml` (stock default, unbranded) + `aj360_app/.chainlit/translations/{ar-SA,bn,da-DK,de-DE,el-GR,en-US,es,fr-FR,gu,he-IL,hi,it,ja,kn,ko,ml,mr,nl,pt-PT,ta,te,zh-CN,zh-TW}.json` (23 files, byte-identical to root copies).
* **Fix:** `git rm -r aj360_app/.chainlit && echo 'aj360_app/.chainlit/' >> .gitignore`. Root `.chainlit/` stays the single source.

### 🔴 2. Stray root `config.toml` shadows the real one (already drifted)
Chainlit only loads `.chainlit/config.toml`; the root copy is dead config that misleads — and the two have diverged on a **security** setting.
* **Affected:** `config.toml` (root, `unsafe_allow_html=false`), `.chainlit/config.toml` (loaded, `unsafe_allow_html=true`).
* **Fix:** reconcile any wanted delta into `.chainlit/config.toml`, then `git rm config.toml`.

### 🔴 3. `app.py` god module + dual-app duplicated logic
The biggest maintainability/scalability risk: a 2,786-line catch-all and the same agent/SQL/GLM logic implemented twice with divergent behavior (the read-only guard had to be fixed in two places).
* **Affected:** `app.py` (123 KB); parallel copies in `aj360_app/aj360_app/core.py` (`execute_sql`, `_dry_run`, `_check_banned_aliases`), `agent.py`, `integrations.py`, `state.py` (41 KB), `aj360_app.py` (61 KB).
* **Fix:** extract a framework-agnostic `ocd_core/` package (GLM client, BigQuery+SQL-guard, MCP registry, Chroma); make both apps thin frontends. Split `app.py` by concern.

### 🟡 4. Packaging: two `requirements.txt`, no `pyproject.toml`, raw freeze
* **Affected:** `requirements.txt` (182-line root freeze, ~7 direct deps buried in ~150 transitives), `aj360_app/requirements.txt` (`reflex==0.9.5.post2`); no `pyproject.toml`.
* **Fix:** root `pyproject.toml` with direct deps + extras (`[project.optional-dependencies] chainlit=…, reflex=…, dev=…`); keep a `requirements.lock` for reproducibility.

### 🟡 5. No installable package → tests load by file path
* **Affected:** `tests/test_sql_guard.py`, `tests/test_auth.py`, `tests/test_mcp_registry.py` (all use `spec_from_file_location`); no `conftest.py`/`pytest.ini`.
* **Fix:** after packaging, replace loaders with real imports; add `pytest.ini` + `conftest.py`.

### 🟡 6. Two virtualenvs + machine-absolute path in committed config
* **Affected:** `venv/` (Py 3.14), `venv312/` (Py 3.12), `mcp_servers.json` (abs interpreter + script paths).
* **Fix:** keep one venv; make `mcp_servers.json` interpreter-agnostic (`"python"` / `sys.executable`) with a repo-relative script path.

### 🟡 7. Overloaded repo root
* **Affected (runtime/data):** `chroma_db/`, `kuzu_db`, `kuzu_db.wal`, `logs/`, `projects/`, `knowledge/`, `_sandbox/`, `agent_memory/`, `.files/`. **(loose docs):** `aj360.md` (748 KB), `aj360-skill-ux-curation-update.md`, `aj360-ux-curation-2026-06-23.md`, `chainlit.md`.
* **Fix:** `src/` (code), `docs/` (notes), one `runtime/` for data via `AJ360_DATA_DIR`.

### 🟡 8. Naming drift + triple-nested module
* **Affected:** `aj360_app/aj360_app/aj360_app.py` (triple token), `aj360_settings.json` (generic content, legacy prefix), `aj360-ux-curation-2026-06-23.md` (date in name), `aj360-skill-ux-curation-update.md` (`-update`).
* **Fix:** rename product-generic files (`aj360_settings.json` → `settings.json`, update the one reader in `core.py`); move curation notes to `docs/`. (Functional `aj360*` dataset/flag identifiers intentionally retained.)

### 🟢 9. Scratch artifacts + large generated lockfile
* **Affected:** `_sandbox/test/`, `agent_memory/test/`, root `reflex_*.log`/`.err` (13, now git-ignored), `aj360_app/reflex.lock/package-lock.json` (301 KB).
* **Fix:** delete scratch dirs/logs from disk; decide whether `reflex.lock/` should be tracked (Reflex regenerates it).

---

## Round 2 — Ops / Quality / Governance (new)

### 🔴 10. No CI pipeline
Tests, the SQL-guard, auth, and MCP-registry checks exist but never run automatically; nothing blocks a regression or a secret from merging.
* **Affected:** absent `.github/workflows/`.
* **Fix:** add `.github/workflows/ci.yml` — matrix on Python 3.12, `pip install -e ".[dev]"`, `ruff check`, `mypy`, `pytest`, and a secret scan (gitleaks). Make it required on PRs.

### 🟡 11. No linter / formatter / type-checker / pre-commit config
No enforced style or typing on a large, mixed codebase.
* **Affected:** absent `pyproject.toml`/`.ruff.toml`/`.flake8`/`mypy.ini`/`.pre-commit-config.yaml`/`.editorconfig`.
* **Fix:** adopt `ruff` (lint+format) + `mypy` config in `pyproject.toml`; add `.pre-commit-config.yaml` running ruff/mypy/gitleaks; add `.editorconfig`.

### 🔴 12. No pre-commit secret scanning (despite a prior leak)
A production GCP service-account key and a populated `.env` were committed and pushed to a **public** repo earlier this session. Nothing prevents a recurrence.
* **Affected:** repo-wide; `.gitignore` is the only guard.
* **Fix:** add `gitleaks`/`trufflehog` as a pre-commit hook **and** a CI gate; document key rotation in `SECURITY.md`. (Outstanding: the leaked SA key + `.env`/GLM secrets still need rotation in GCP/Z.ai.)

### 🟡 13. No governance files
* **Affected:** absent `LICENSE`, `SECURITY.md`, `CONTRIBUTING.md`, `CODEOWNERS`.
* **Fix:** add a `LICENSE` (the repo is published), a `SECURITY.md` (reporting + the read-only/credentials posture), `CONTRIBUTING.md` (setup, single venv, `pip install -e`), and `CODEOWNERS`.

### 🟡 14. Apps are not containerized
`docker-compose.yml` runs only Postgres; there is no image for the Chainlit or Reflex app, so the deploy story is manual/Windows-coupled.
* **Affected:** `docker-compose.yml` (postgres only); absent `Dockerfile`, `.dockerignore`.
* **Fix:** add a `Dockerfile` (or one per app) and `.dockerignore` (exclude `venv*/`, `.web/`, `node_modules/`, data dirs); add the app services to compose with the Postgres dependency.

### 🟡 15. Low test coverage
3 test files for 17 source modules; the highest-risk code is untested.
* **Affected:** untested — `app.py` `run_agent`/`stream_llm`/`run_sql` execution path/charts/projects; `aj360_app/aj360_app/agent.py`/`state.py`/`core.py execute_sql`. Tested — `sql_guard`, `auth`, `mcp_registry`.
* **Fix:** after packaging, add unit tests for the GLM stream parser (reasoning/tool deltas), the cost/approval gate, and project CRUD; add a coverage gate in CI.

### 🟢 16. Binary committed as a loose root file
* **Affected:** `aj360-daily-insights.skill` (a ZIP — `PK\x03\x04` header — at repo root).
* **Fix:** move to a `skills/` (or `docs/`) location with a documented purpose, or unpack it; don't keep opaque binaries at the root.

### 🟢 17. File-based audit log without rotation
* **Affected:** `app.py` (`AUDIT_LOG = "./logs/agent_audit.jsonl"`, append-only).
* **Fix:** use `RotatingFileHandler`/`logging.handlers` or ship to a structured sink; document retention. Ensure no PII/secrets are logged (auth attempts currently log usernames).

---

## Prioritized remediation roadmap

1. **Now (safe deletes):** #1 stray `.chainlit`, #2 stray `config.toml`, #9/#16 scratch & binary cleanup.
2. **Security/CI (this sprint):** #12 secret-scan + #10 CI + #13 `LICENSE`/`SECURITY.md`; complete the outstanding **secret rotation**.
3. **Packaging (mid-term):** #4 `pyproject.toml` → #5 real imports in tests → #11 ruff/mypy/pre-commit → #15 coverage.
4. **Architecture (the real investment):** #3 shared `ocd_core/` package + split god module; #7 `src/`+`runtime/` layout; #6/#8 env & naming cleanup; #14 containerization.

## Verified-not-an-issue
* `public/projects.svg` at root is **correct** — Chainlit serves static assets from a root `public/` dir, and `app.py` references `/public/projects.svg`.
* Empty `aj360_app/aj360_app/__init__.py` is an idiomatic package marker.
* `.web/` and `__pycache__/` are correctly git-ignored.
