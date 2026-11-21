# Phase 1 — Consolidate the Core — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eliminate the domain-logic duplication between the Chainlit app (`app.py`) and the Reflex app (`legacy_frontend/`) by consolidating every framework-agnostic concern into a single installable `backend/ocd_core/` package, while both apps keep working unchanged.

**Architecture:** `backend/ocd_core/` becomes the single source of truth (config, guards, helpers, observability, skills, commands, BigQuery/LLM/Chroma access, projects/conversations/KB, the agent loop, integrations). The Reflex app imports `ocd_core` directly (still in-process — no FastAPI, no HTTP yet). Logic that lives **only** in `app.py` (rate limiter, project allowlist, rotating audit log, eager catalog rebuild, slash-command + skill-trigger parsing) is salvaged into `ocd_core`, **decoupled from Chainlit's `cl.user_session`**, before `app.py` is retired in a later phase.

**Tech Stack:** Python 3.12 · pytest · setuptools (editable install) · ruff/mypy · ZhipuAI (GLM) · google-cloud-bigquery · chromadb · Reflex (frontend, unchanged this phase).

---

## Scope & sequencing notes (read first)

- **Spec source of truth:** `docs/superpowers/specs/2026-06-27-two-service-refactor-design.md`. This plan implements **Phase 1 only** (spec §10.1) plus the §6 salvage directives.
- **Physical location:** Phase 1 creates **`backend/ocd_core/`** as the package's final home (spec §4). The import path stays the top-level `ocd_core` (the `backend/` dir is a source root via an editable install), so **no import statements change** when code moves there. The Reflex app stays at `legacy_frontend/` this phase and is relocated to `frontend/` in Phase 4.
- **Parity bar:** Phase 1 changes **structure, not behavior**. Every salvaged/moved function must behave identically. Where the source has a known wart (e.g. the allowlist's fragile substring match), port it faithfully and add a test that *documents* the wart with a `# KNOWN-WART` comment — do not "fix" it here.
- **Config module:** Implemented as a plain module exposing the existing UPPER_CASE constant names (parity, zero new access pattern). Wrapping in `pydantic-settings` (spec §4) is a trivial later refinement, deliberately deferred to keep this phase behavior-neutral.
- **`core.py` shim strategy:** As each concern moves into `ocd_core`, `legacy_frontend/core.py` (and `integrations.py`, `agent.py`) keep their public names by **re-exporting** from `ocd_core` (`from ocd_core.x import y`). This keeps `state.py`/`legacy_frontend.py` import sites untouched until Phase 4. The final slice removes the now-empty originals.
- **Integration sanity check (used in every slice):** the two-command smoke test in Appendix A. Run it at the end of every slice; both apps must import and the consolidated unit tests must be green.

---

## File structure (created/modified across Phase 1)

**Created (new):**
- `backend/pyproject.toml` — backend package (editable-installed)
- `backend/ocd_core/config.py` — single source of all env-driven constants
- `backend/ocd_core/util.py` — pure helpers (slugify, byte/format/time, chunk-id, flatten-fields)
- `backend/ocd_core/observability.py` — `observe`, `audit` (rotating), `check_rate_limit`
- `backend/ocd_core/skills.py` — skill loading + word-boundary matching (canonical)
- `backend/ocd_core/commands.py` — UI-agnostic slash-command parser + skill resolution
- `backend/ocd_core/bigquery.py`, `schema_catalog.py`, `llm.py`
- `backend/ocd_core/projects.py`, `conversations.py`, `knowledge.py`
- `backend/ocd_core/agent.py`
- `backend/ocd_core/integrations/__init__.py`, `plugins.py`, `connectors.py`, `mcp_registry.py`, `web.py`
- `backend/tests/` — real-import unit tests for everything above

**Moved:**
- `ocd_core/{__init__.py,sql_guard.py}` → `backend/ocd_core/`
- `tests/test_ocd_core_sql_guard.py` → `backend/tests/`
- domain code out of `legacy_frontend/{core,agent,integrations,mcp_registry}.py`

**Modified:**
- `pyproject.toml` (root) — drop the `ocd_core` package declaration (now in `backend/`)
- `legacy_frontend/{core,agent,integrations,mcp_registry}.py` — become thin re-export shims, then trimmed
- root `app.py` — **not touched this phase** (retired in Phase 5); it keeps importing `ocd_core.sql_guard`

---

## Task 0: Backend package scaffold

Establish `backend/ocd_core/` as an editable-installed package by relocating the only module that's already extracted (`sql_guard`). Nothing else moves yet — this slice proves the new home is importable by both apps and by tests.

**Files:**
- Create: `backend/pyproject.toml`
- Move: `ocd_core/__init__.py` → `backend/ocd_core/__init__.py`
- Move: `ocd_core/sql_guard.py` → `backend/ocd_core/sql_guard.py`
- Move: `tests/test_ocd_core_sql_guard.py` → `backend/tests/test_sql_guard.py`
- Create: `backend/tests/__init__.py` (empty)
- Modify: `pyproject.toml` (root) — remove `ocd_core` from `[tool.setuptools] packages`

- [ ] **Step 1: Write the failing test** (`backend/tests/test_packaging.py`)

```python
def test_ocd_core_importable_from_installed_package():
    import ocd_core
    from ocd_core import sql_guard
    assert hasattr(sql_guard, "check_banned_aliases")
    # the package now lives under backend/, not repo-root
    assert "backend" in ocd_core.__file__.replace("\\", "/")
```

- [ ] **Step 2: Run it — expect FAIL**

Run: `pytest backend/tests/test_packaging.py -v`
Expected: FAIL — `ocd_core.__file__` still points at the repo-root `ocd_core/` (assert on "backend" fails), or ModuleNotFound if the move happened first.

- [ ] **Step 3: Create `backend/pyproject.toml`**

```toml
[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[project]
name = "ocd-backend"
version = "0.3.0"
requires-python = ">=3.12"
dependencies = [
  "zhipuai",
  "google-cloud-bigquery",
  "google-auth",
  "chromadb",
  "pandas",
  "pdfplumber",
  "mcp",
  "python-dotenv",
]

[project.optional-dependencies]
dev = ["pytest", "ruff", "mypy"]

[tool.setuptools]
packages = ["ocd_core", "ocd_core.integrations"]
package-dir = {"" = "."}

[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-q"
```

- [ ] **Step 4: Move the files** (preserve history)

```bash
git mv ocd_core/__init__.py backend/ocd_core/__init__.py
git mv ocd_core/sql_guard.py backend/ocd_core/sql_guard.py
git mv tests/test_ocd_core_sql_guard.py backend/tests/test_sql_guard.py
```

Then edit `backend/tests/test_sql_guard.py`: delete its `sys.path.insert(...)` shim and the path computation; replace with a plain `from ocd_core import sql_guard` (it is now installed). Create empty `backend/tests/__init__.py`.

- [ ] **Step 5: Drop `ocd_core` from root `pyproject.toml`**

In root `pyproject.toml`, remove `"ocd_core"` from `[tool.setuptools] packages` (and any `ocd_core*` include) so the package is owned only by `backend/`.

- [ ] **Step 6: Install editable + run tests**

Run:
```bash
pip install -e "./backend[dev]"
pytest backend/tests -v
```
Expected: PASS (both `test_packaging.py` and the moved `test_sql_guard.py`).

- [ ] **Step 7: Integration sanity (Appendix A) + commit**

```bash
python -c "import ocd_core.sql_guard; import app" 2>NUL || python -c "import ocd_core.sql_guard"
cd legacy_frontend && python -c "import sys; sys.path.insert(0,'legacy_frontend'); import ocd_core.sql_guard" && cd ..
git add -A && git commit -m "refactor(core): scaffold backend/ocd_core editable package (move sql_guard)"
```
Expected: imports succeed; both apps still resolve `ocd_core.sql_guard`.

---

## Task 1: `ocd_core/config.py` — single source of configuration

Today `PROJECT_ID`, `CATALOG_DATASETS`, `MAX_*`, model names, paths, rate-limit and audit knobs are defined **twice** (root `app.py` and `legacy_frontend/core.py`) with drift risk. Centralize them, parity-exact.

**Files:**
- Create: `backend/ocd_core/config.py`
- Create: `backend/tests/test_config.py`
- Modify: `legacy_frontend/core.py` (replace the duplicated constant block with imports)

- [ ] **Step 1: Write the failing test** (`backend/tests/test_config.py`)

```python
import importlib

def test_defaults_match_current_values(monkeypatch):
    for k in ("GCP_PROJECT_ID", "CATALOG_DATASETS", "MAX_BYTES_BILLED_GB",
              "QUERY_TIMEOUT_SEC", "RATE_LIMIT_QUERIES", "RATE_LIMIT_WINDOW_SEC"):
        monkeypatch.delenv(k, raising=False)
    cfg = importlib.reload(importlib.import_module("ocd_core.config"))
    assert cfg.PROJECT_ID == "example-analytics-project-01"
    assert cfg.CATALOG_DATASETS == [
        "analytics", "analytics_platform", "analytics_search_analytics",
        "warehouse_models", "analytics_ds", "analytics_monitoring",
        "analytics_marts", "analytics_acquisition_analytics"]
    assert cfg.MAX_BYTES_BILLED == 100 * (1024 ** 3)
    assert cfg.QUERY_TIMEOUT_SEC == 300
    assert cfg.MAX_RETURN_ROWS == 50 and cfg.MAX_STORED_ROWS == 5000
    assert cfg.RATE_LIMIT_QUERIES == 20 and cfg.RATE_LIMIT_WINDOW_SEC == 60

def test_env_override(monkeypatch):
    monkeypatch.setenv("GCP_PROJECT_ID", "my-proj")
    monkeypatch.setenv("CATALOG_DATASETS", "a, b ,c")
    cfg = importlib.reload(importlib.import_module("ocd_core.config"))
    assert cfg.PROJECT_ID == "my-proj"
    assert cfg.CATALOG_DATASETS == ["a", "b", "c"]
```

- [ ] **Step 2: Run it — expect FAIL**

Run: `pytest backend/tests/test_config.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'ocd_core.config'`.

- [ ] **Step 3: Write `backend/ocd_core/config.py`**

Mirror the **exact** current env reads (values harvested from `legacy_frontend/core.py` and root `app.py`). Use the same names so call sites are unchanged.

```python
"""Single source of truth for env-driven configuration (parity with the
pre-refactor app.py + legacy_frontend/core.py constants)."""
import hashlib
import os
from pathlib import Path

# --- paths (data dir override) ---
REPO_ROOT = Path(os.getenv("OCD_DATA_DIR", "")).resolve() if os.getenv("OCD_DATA_DIR") \
    else Path(__file__).resolve().parents[2]
PROJECTS_DIR = Path(os.getenv("PROJECTS_DIR", str(REPO_ROOT / "projects")))
KNOWLEDGE_DIR = Path(os.getenv("KNOWLEDGE_DIR", str(REPO_ROOT / "knowledge")))
CHROMA_PATH = os.getenv("CHROMA_PATH", str(REPO_ROOT / "chroma_db"))
SKILLS_DIR = Path(os.getenv("SKILLS_DIR", str(REPO_ROOT / "skills")))
PLUGINS_DIR = Path(os.getenv("PLUGINS_DIR", str(REPO_ROOT / "plugins")))

# --- BigQuery ---
PROJECT_ID = os.getenv("GCP_PROJECT_ID", "example-analytics-project-01")
_GB = 1024 ** 3
MAX_BYTES_BILLED = int(os.getenv("MAX_BYTES_BILLED_GB", "100")) * _GB
QUERY_TIMEOUT_SEC = int(os.getenv("QUERY_TIMEOUT_SEC", "300"))
MAX_RETURN_ROWS = 50
MAX_STORED_ROWS = 5000
MAX_COLS_PER_CARD = 200
MAX_TABLE_ROWS_UI = 50
CATALOG_DATASETS = [d.strip() for d in os.getenv(
    "CATALOG_DATASETS",
    "analytics,analytics_platform,analytics_search_analytics,warehouse_models,"
    "analytics_ds,analytics_monitoring,analytics_marts,analytics_acquisition_analytics"
).split(",") if d.strip()]
_CATALOG_VERSION = hashlib.md5(",".join(sorted(CATALOG_DATASETS)).encode()).hexdigest()[:12]
_CATALOG_VERSION_FILE = KNOWLEDGE_DIR / ".catalog_version"
GENERIC_COLS = {
    "date", "name", "value", "type", "key", "status", "id", "count", "total",
    "country", "city", "region", "month", "week", "weekday", "source", "medium",
    "device", "category", "title", "description", "label", "url", "hour", "day",
}

# --- models ---
AGENT_MODEL = os.getenv("AGENT_MODEL", os.getenv("PLANNER_MODEL", "glm-4-plus"))
FLASH_MODEL = os.getenv("FLASH_MODEL", "glm-4-flash")
VISION_MODEL = os.getenv("VISION_MODEL", "glm-4v-plus")
_glm_default = f"{AGENT_MODEL},glm-4.5-air,glm-4-flash,glm-4-long"
GLM_MODELS = list(dict.fromkeys(
    m.strip() for m in os.getenv("GLM_MODELS", _glm_default).split(",") if m.strip()))

# --- effort + settings ---
EFFORT_LEVELS = ["Low", "Medium", "High", "Max"]
DEFAULT_SETTINGS = {"model": AGENT_MODEL, "effort": "High", "theme": "light"}
SETTINGS_FILE = REPO_ROOT / "settings.json"

# --- projects / conversations ---
PROJECT_CAPACITY_BYTES = int(os.getenv("PROJECT_CAPACITY_MB", "50")) * 1024 * 1024
CONV_MAX_MESSAGES = int(os.getenv("CONV_MAX_MESSAGES", "400"))
GENERAL_ID = "general"
GENERAL_NAME = "General"

# --- rate limiting (salvaged from app.py) ---
RATE_LIMIT_QUERIES = int(os.getenv("RATE_LIMIT_QUERIES", "20"))
RATE_LIMIT_WINDOW_SEC = int(os.getenv("RATE_LIMIT_WINDOW_SEC", "60"))

# --- audit log (salvaged from app.py) ---
AUDIT_LOG = os.getenv("AUDIT_LOG", "./logs/agent_audit.jsonl")
AUDIT_LOG_MAX_BYTES = int(os.getenv("AUDIT_LOG_MAX_BYTES", str(10 * 1024 * 1024)))
AUDIT_LOG_BACKUPS = int(os.getenv("AUDIT_LOG_BACKUPS", "5"))

# --- write posture (kept; intentionally analytics-prefixed per project memory) ---
ALLOW_WRITES = os.getenv("OCD_ALLOW_WRITES", "").lower() in ("1", "true", "yes")
```

- [ ] **Step 4: Run it — expect PASS**

Run: `pytest backend/tests/test_config.py -v`
Expected: PASS (both tests).

- [ ] **Step 5: Repoint `legacy_frontend/core.py` at the shared config**

In `legacy_frontend/core.py`, delete the duplicated constant definitions (the harvested lines: REPO_ROOT/PROJECTS_DIR/KNOWLEDGE_DIR/CHROMA_PATH ~28-39, model + effort + settings ~48-74, PROJECT_ID..GENERIC_COLS ~583-603, capacity/conv ~45,236-240, etc.) and replace with a single import block near the top:

```python
from ocd_core.config import (
    REPO_ROOT, PROJECTS_DIR, KNOWLEDGE_DIR, CHROMA_PATH, SKILLS_DIR, PLUGINS_DIR,
    PROJECT_ID, MAX_BYTES_BILLED, QUERY_TIMEOUT_SEC, MAX_RETURN_ROWS,
    MAX_STORED_ROWS, MAX_COLS_PER_CARD, MAX_TABLE_ROWS_UI, CATALOG_DATASETS,
    _CATALOG_VERSION, _CATALOG_VERSION_FILE, GENERIC_COLS, AGENT_MODEL,
    FLASH_MODEL, VISION_MODEL, GLM_MODELS, EFFORT_LEVELS, DEFAULT_SETTINGS,
    PROJECT_CAPACITY_BYTES, CONV_MAX_MESSAGES, GENERAL_ID, GENERAL_NAME,
)
```
Keep `_GB`, `_REGISTRY_FILE`, `_SETTINGS_FILE`, `EFFORT_DESCRIPTIONS`, `_TEXT_EXTS` as-is in `core.py` for now (UI/local concerns; relocated later).

- [ ] **Step 6: Verify Reflex still imports + sanity (Appendix A)**

Run: `cd legacy_frontend && python -c "from legacy_frontend import core; print(core.PROJECT_ID, len(core.CATALOG_DATASETS))" && cd ..`
Expected: prints `example-analytics-project-01 8`.

- [ ] **Step 7: Commit**

```bash
git add -A && git commit -m "refactor(core): centralize config in ocd_core.config (de-dup app.py/core.py)"
```

---

## Task 2: `ocd_core/util.py` — pure helpers

`_slugify`, byte/size formatting, relative-time, `_chunk_id`, `_flatten_fields` are duplicated across `app.py` and `core.py`. They are pure and trivially testable — move them first among the domain code.

**Files:**
- Create: `backend/ocd_core/util.py`
- Create: `backend/tests/test_util.py`
- Modify: `legacy_frontend/core.py` (re-export from util)

- [ ] **Step 1: Write the failing test** (`backend/tests/test_util.py`)

```python
from ocd_core import util

def test_slugify():
    assert util.slugify("Hello World!") == "hello-world"
    assert util.slugify("  A/B  C ") == "a-b-c"
    assert util.slugify("") == "untitled"

def test_fmt_bytes():
    assert util.fmt_bytes(0) == "0 B"
    assert util.fmt_bytes(1024) == "1.0 KB"
    assert util.fmt_bytes(1024 ** 3) == "1.0 GB"

def test_chunk_id_is_stable_and_content_sensitive():
    a = util.chunk_id("f.md", 3, "hello")
    assert a == util.chunk_id("f.md", 3, "hello")
    assert a != util.chunk_id("f.md", 3, "world")

def test_flatten_fields_dotted_paths():
    fields = [
        {"name": "a", "type": "STRING"},
        {"name": "rec", "type": "RECORD", "fields": [{"name": "b", "type": "INT64"}]},
    ]
    assert set(util.flatten_fields(fields)) == {"a", "rec.b"}
```

- [ ] **Step 2: Run it — expect FAIL**

Run: `pytest backend/tests/test_util.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'ocd_core.util'`.

- [ ] **Step 3: Write `backend/ocd_core/util.py`**

Port the existing bodies verbatim (from `legacy_frontend/core.py`: `_slugify` 137, `_fmt_size` 587, `relative_time` 605, `_chunk_id` 560, `_flatten_fields` 668). Expose **public** names (`slugify`, `fmt_bytes`, `relative_time`, `format_date`, `chunk_id`, `flatten_fields`) and keep private aliases for the old names.

```python
"""Pure, dependency-free helpers shared by both app surfaces."""
import hashlib
import re
from datetime import datetime, timezone


def slugify(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    return s or "untitled"


def fmt_bytes(n) -> str:
    try:
        n = float(n)
    except (TypeError, ValueError):
        return "0 B"
    for unit in ("B", "KB", "MB", "GB", "TB", "PB"):
        if abs(n) < 1024.0:
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024.0
    return f"{n:.1f} EB"


def chunk_id(filename: str, idx: int, content: str) -> str:
    h = hashlib.md5(f"{filename}:{idx}:{content[:500]}".encode()).hexdigest()[:16]
    return f"{filename}:{idx}:{h}"


def flatten_fields(fields, prefix: str = "") -> list[str]:
    out: list[str] = []
    for f in fields or []:
        name = f"{prefix}{f['name']}"
        if f.get("type") == "RECORD" and f.get("fields"):
            out.extend(flatten_fields(f["fields"], prefix=f"{name}."))
        else:
            out.append(name)
    return out


def relative_time(value) -> str:
    # port the existing body from core.py:605 verbatim
    ...


def format_date(iso_str: str) -> str:
    # port the existing body from core.py:596 verbatim
    ...


# back-compat private aliases (so existing call sites keep working pre-shim)
_slugify = slugify
_fmt_size = _fmt_bytes = fmt_bytes
_chunk_id = chunk_id
_flatten_fields = flatten_fields
```

> NOTE TO IMPLEMENTER: replace the two `...` bodies with the exact current
> implementations from `legacy_frontend/core.py` (`relative_time` line 605,
> `format_date` line 596). Then extend `test_util.py` with one assertion each
> (`format_date("2026-06-27T00:00:00Z")` non-empty; `relative_time` of "now"
> contains "ago" or "just"). Keep behavior identical.

- [ ] **Step 4: Run it — expect PASS**

Run: `pytest backend/tests/test_util.py -v`
Expected: PASS.

- [ ] **Step 5: Repoint `core.py`** — replace the five helper bodies with `from ocd_core.util import slugify as _slugify, fmt_bytes, chunk_id as _chunk_id, flatten_fields as _flatten_fields, relative_time, format_date` and delete the old defs.

- [ ] **Step 6: Sanity (Appendix A) + commit**

```bash
pytest backend/tests -q
git add -A && git commit -m "refactor(core): move pure helpers to ocd_core.util"
```

---

## Task 3: `ocd_core/observability.py` — observe + rotating audit + rate limiter (SALVAGE 1 & 3)

Salvage app.py's `_observe`, `audit` (RotatingFileHandler) and the per-user sliding-window rate limiter — **decoupled from Chainlit**: `check_rate_limit` takes a `user_id` and an injectable clock.

**Files:**
- Create: `backend/ocd_core/observability.py`
- Create: `backend/tests/test_observability.py`

- [ ] **Step 1: Write the failing test** (`backend/tests/test_observability.py`)

```python
import json
from ocd_core import observability as obs

def test_rate_limit_sliding_window():
    rl = obs.RateLimiter(limit=2, window_sec=60)
    clock = [1000.0]
    now = lambda: clock[0]
    assert rl.check("u1", now=now) is True   # 1
    assert rl.check("u1", now=now) is True   # 2
    assert rl.check("u1", now=now) is False  # blocked
    clock[0] += 61                           # window slides
    assert rl.check("u1", now=now) is True
    # isolation between users
    assert rl.check("u2", now=now) is True

def test_audit_writes_jsonl(tmp_path):
    log = tmp_path / "audit.jsonl"
    a = obs.Audit(path=str(log), max_bytes=10_000, backups=1)
    a.write({"event": "x", "user": "u1"})
    line = log.read_text(encoding="utf-8").strip().splitlines()[-1]
    rec = json.loads(line)
    assert rec["event"] == "x" and rec["user"] == "u1" and "ts" in rec

def test_observe_emits_json(capsys):
    obs.observe("hello", n=1)
    err = capsys.readouterr().err
    assert '"event": "hello"' in err and '"n": 1' in err
```

- [ ] **Step 2: Run it — expect FAIL** (`ModuleNotFoundError`)

Run: `pytest backend/tests/test_observability.py -v`

- [ ] **Step 3: Write `backend/ocd_core/observability.py`**

Port the salvaged bodies; wrap rate-limiter and audit as small classes so they're injectable/testable (no `cl.user_session`). Read defaults from `ocd_core.config`.

```python
"""Structured logging, rotating audit trail, and rate limiting.
Salvaged from app.py and decoupled from Chainlit (#1, #3)."""
import json
import logging
import logging.handlers
import os
import sys
import threading
import time
from datetime import datetime, timezone

from . import config

_logger = logging.getLogger("ocd_agent")
if not _logger.handlers:
    _logger.setLevel(logging.INFO)
    _sh = logging.StreamHandler()
    _sh.setFormatter(logging.Formatter("%(message)s"))
    _logger.addHandler(_sh)


def observe(event: str, **fields):
    record = {"event": event, "ts": datetime.now(timezone.utc).isoformat(), **fields}
    _logger.info(json.dumps(record, default=str))


class Audit:
    def __init__(self, path=None, max_bytes=None, backups=None):
        path = path or config.AUDIT_LOG
        self._logger = logging.getLogger(f"ocd_audit.{path}")
        self._logger.setLevel(logging.INFO)
        self._logger.propagate = False
        if not self._logger.handlers:
            try:
                os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
                fh = logging.handlers.RotatingFileHandler(
                    path, maxBytes=max_bytes or config.AUDIT_LOG_MAX_BYTES,
                    backupCount=backups if backups is not None else config.AUDIT_LOG_BACKUPS,
                    encoding="utf-8")
                fh.setFormatter(logging.Formatter("%(message)s"))
                self._logger.addHandler(fh)
            except Exception as e:  # non-fatal: audit must never break a query
                print(f"[AUDIT] not writable ({path}): {e}", file=sys.stderr)

    def write(self, event: dict):
        try:
            event = {"ts": datetime.now(timezone.utc).isoformat(), **event}
            self._logger.info(json.dumps(event, default=str))
        except Exception as e:
            print(f"[AUDIT] write failed: {e}", file=sys.stderr)


class RateLimiter:
    def __init__(self, limit=None, window_sec=None):
        self.limit = limit if limit is not None else config.RATE_LIMIT_QUERIES
        self.window = window_sec if window_sec is not None else config.RATE_LIMIT_WINDOW_SEC
        self._lock = threading.Lock()
        self._times: dict[str, list[float]] = {}

    def check(self, user_id: str, now=time.time) -> bool:
        t = now()
        with self._lock:
            times = [x for x in self._times.get(user_id, []) if t - x < self.window]
            if len(times) >= self.limit:
                self._times[user_id] = times
                return False
            times.append(t)
            self._times[user_id] = times
            return True


# module-level singletons mirroring app.py's globals
audit_log = Audit()
rate_limiter = RateLimiter()


def audit(event: dict):
    audit_log.write(event)


def check_rate_limit(user_id: str) -> bool:
    return rate_limiter.check(user_id)
```

- [ ] **Step 4: Run it — expect PASS**

Run: `pytest backend/tests/test_observability.py -v`

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "refactor(core): salvage observe/audit/rate-limit into ocd_core.observability (#1,#3)"
```

---

## Task 4: project allowlist guard in `ocd_core/sql_guard.py` (SALVAGE 2)

Salvage the per-project table-allowlist enforcement out of `app.py`'s `run_sql` into a pure guard function. **Port the known-fragile substring match faithfully** (parity), with a test that documents the wart.

**Files:**
- Modify: `backend/ocd_core/sql_guard.py` (add `tables_off_allowlist`)
- Create: `backend/tests/test_allowlist.py`

- [ ] **Step 1: Write the failing test** (`backend/tests/test_allowlist.py`)

```python
from ocd_core import sql_guard

def test_empty_allowlist_allows_everything():
    assert sql_guard.tables_off_allowlist("SELECT * FROM anything", []) is False

def test_allowed_table_present_passes():
    assert sql_guard.tables_off_allowlist(
        "SELECT x FROM analytics.events", ["analytics.events"]) is False

def test_no_allowed_table_is_blocked():
    assert sql_guard.tables_off_allowlist(
        "SELECT x FROM other.table", ["analytics.events"]) is True

def test_known_wart_substring_match_is_case_insensitive():
    # KNOWN-WART: substring (not parsed-reference) match — faithful to app.py.
    assert sql_guard.tables_off_allowlist(
        "SELECT 1 -- mentions Analytics.EVENTS in a comment", ["analytics.events"]) is False
```

- [ ] **Step 2: Run it — expect FAIL** (`AttributeError: tables_off_allowlist`)

Run: `pytest backend/tests/test_allowlist.py -v`

- [ ] **Step 3: Add the guard to `sql_guard.py`**

```python
def tables_off_allowlist(sql: str, allowlist: list[str]) -> bool:
    """True if a non-empty allowlist is in force and NONE of its tables appear
    in the SQL. KNOWN-WART: substring match (faithful to app.py run_sql); should
    move to parsed referenced_tables in a later hardening pass."""
    if not allowlist:
        return False
    low = sql.lower()
    return not any(t.lower() in low for t in allowlist)
```

- [ ] **Step 4: Run it — expect PASS**

Run: `pytest backend/tests/test_allowlist.py -v`

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "refactor(core): salvage project allowlist guard into ocd_core.sql_guard (#2)"
```

---

## Task 5: `ocd_core/skills.py` — canonical skill loader + matcher

Consolidate the **duplicated** skill logic (`app.py` `Skill`/`_load_skills`/`matches_text`/`matches_files` and `integrations.py` `_split_frontmatter`/`list_skills`/`matching_skill`) into one UI-agnostic module supporting both fenced and bare frontmatter, word-boundary text triggers, and filename triggers.

**Files:**
- Create: `backend/ocd_core/skills.py`
- Create: `backend/tests/test_skills.py`

- [ ] **Step 1: Write the failing test** (`backend/tests/test_skills.py`)

```python
from ocd_core import skills

def test_split_frontmatter_fenced():
    front, body = skills.split_frontmatter("---\nname: x\nauto: true\n---\nBODY")
    assert "name: x" in front and body == "BODY"

def test_split_frontmatter_bare():
    front, body = skills.split_frontmatter("name: hero\ntriggers: hero\n# Heading\ntext")
    assert any(l.startswith("name:") for l in front)
    assert body.startswith("# Heading")

def test_list_skills_skips_disabled(tmp_path):
    (tmp_path / "a.md").write_text("name: a\nauto: true\ntriggers: foo\n\nDo A", encoding="utf-8")
    (tmp_path / "b.md").write_text("name: b\ndisabled: true\n\nDo B", encoding="utf-8")
    got = skills.list_skills(tmp_path)
    names = {s["name"] for s in got}
    assert names == {"a"}

def test_matching_skill_word_boundary(tmp_path):
    (tmp_path / "hero.md").write_text(
        "name: hero\nauto: true\ntriggers: hero, carousel\n\nHero help", encoding="utf-8")
    assert skills.matching_skill("show the hero rail", tmp_path) == "hero"
    assert skills.matching_skill("heroic effort", tmp_path) == ""   # boundary, not substring

def test_matching_skill_filename_trigger(tmp_path):
    (tmp_path / "csv.md").write_text(
        "name: csv\nauto: true\nfile_triggers: .csv\n\nCSV help", encoding="utf-8")
    assert skills.matching_skill("", tmp_path, filenames=["data.csv"]) == "csv"
```

- [ ] **Step 2: Run it — expect FAIL** (`ModuleNotFoundError`)

Run: `pytest backend/tests/test_skills.py -v`

- [ ] **Step 3: Write `backend/ocd_core/skills.py`**

Merge the two implementations (frontmatter parsing from `integrations._split_frontmatter` + `_load_skills`'s field set; matching from `matching_skill` + `Skill.matches_files`). `SKILLS_DIR` default comes from `config`.

```python
"""Skill discovery + auto-trigger matching (canonical; merges app.py + integrations.py)."""
import re
from pathlib import Path

from . import config

_FIELDS = {"name", "description", "auto", "triggers", "file_triggers",
           "disabled", "references"}


def split_frontmatter(raw: str) -> tuple[list[str], str]:
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", raw, re.DOTALL)
    if m:
        return m.group(1).splitlines(), m.group(2).strip()
    lines = raw.splitlines()
    front, body_start = [], len(lines)
    for i, line in enumerate(lines):
        key = line.split(":", 1)[0].strip().lower() if ":" in line else None
        if key in _FIELDS:
            front.append(line)
        else:
            body_start = i
            break
    return front, "\n".join(lines[body_start:]).strip()


def _parse(raw: str, stem: str) -> dict | None:
    front, body = split_frontmatter(raw)
    d = {"name": stem, "description": "", "instructions": body or raw.strip(),
         "auto": False, "triggers": [], "file_triggers": [], "references": [],
         "disabled": False}
    for line in front:
        if ":" not in line:
            continue
        k, _, v = line.partition(":")
        k, v = k.strip().lower(), v.strip()
        if k in ("name", "description"):
            d[k] = v
        elif k in ("auto", "disabled"):
            d[k] = v.lower() in ("true", "yes", "1")
        elif k in ("triggers", "file_triggers", "references"):
            d[k] = [t.strip() for t in v.split(",") if t.strip()]
    if d["disabled"]:
        return None
    return d


def list_skills(skills_dir: Path | None = None) -> list[dict]:
    d = Path(skills_dir or config.SKILLS_DIR)
    if not d.is_dir():
        return []
    out = []
    for p in sorted(d.glob("*.md")):
        try:
            parsed = _parse(p.read_text(encoding="utf-8"), p.stem)
        except Exception:
            continue
        if parsed:
            out.append(parsed)
    return out


def get_skill(name: str, skills_dir: Path | None = None) -> dict | None:
    return next((s for s in list_skills(skills_dir) if s["name"] == name), None)


def matching_skill(text: str, skills_dir: Path | None = None,
                   filenames: list[str] | None = None) -> str:
    low = (text or "").lower()
    for s in list_skills(skills_dir):
        if not s["auto"]:
            continue
        for t in s["triggers"]:
            if re.search(r"\b" + re.escape(t.lower()) + r"\b", low):
                return s["name"]
        for ft in s["file_triggers"]:
            if any(ft.lower() in (fn or "").lower() for fn in (filenames or [])):
                return s["name"]
    return ""
```

- [ ] **Step 4: Run it — expect PASS**

Run: `pytest backend/tests/test_skills.py -v`

- [ ] **Step 5: Repoint `integrations.py`** — replace its `_split_frontmatter`, `list_skills`, `get_skill`, `matching_skill` with `from ocd_core.skills import split_frontmatter as _split_frontmatter, list_skills, get_skill, matching_skill`. Run the existing integrations import path.

- [ ] **Step 6: Sanity + commit**

```bash
cd legacy_frontend && python -c "from legacy_frontend import integrations; print(integrations.matching_skill('hero'))" && cd ..
git add -A && git commit -m "refactor(core): consolidate skill loader/matcher into ocd_core.skills"
```

---

## Task 6: `ocd_core/commands.py` — UI-agnostic slash-command parser (SALVAGE 5, §6 directive)

The crux of your §6 directive: lift slash-command parsing and explicit/auto skill resolution out of the Chainlit `on_message` shell into a pure parser that the CLI, Reflex, and any API client can share. **No execution, no `cl.user_session`** — it returns a structured intent.

**Files:**
- Create: `backend/ocd_core/commands.py`
- Create: `backend/tests/test_commands.py`

- [ ] **Step 1: Write the failing test** (`backend/tests/test_commands.py`)

```python
from ocd_core import commands

def test_parse_known_commands():
    assert commands.parse("/projects").name == "projects"
    p = commands.parse("/project Al Jazeera")
    assert p.name == "project" and p.arg == "Al Jazeera"
    assert commands.parse("/set-instructions do X").name == "set_instructions"
    assert commands.parse("/skills").name == "skills"
    assert commands.parse("/reload-skills").name == "reload_skills"
    assert commands.parse("/refresh-catalog").name == "refresh_catalog"
    assert commands.parse("/rebuild-catalog").name == "refresh_catalog"  # alias
    assert commands.parse("/learn-finding the thing").name == "learn_finding"
    assert commands.parse("/lint-knowledge").name == "lint_knowledge"

def test_plain_message_is_not_a_command():
    p = commands.parse("how many users last week?")
    assert p.name is None and p.arg == "how many users last week?"

def test_resolve_explicit_skill_strips_prefix(tmp_path):
    (tmp_path / "hero.md").write_text(
        "name: hero\nauto: true\ntriggers: hero\n\nHero help", encoding="utf-8")
    goal, skill, via_auto = commands.resolve_skill("/hero break it down", skills_dir=tmp_path)
    assert skill == "hero" and via_auto is False and goal == "break it down"

def test_resolve_explicit_skill_no_arg_gets_default_goal(tmp_path):
    (tmp_path / "hero.md").write_text("name: hero\nauto: true\ntriggers: hero\n\nx", encoding="utf-8")
    goal, skill, via_auto = commands.resolve_skill("/hero", skills_dir=tmp_path)
    assert skill == "hero" and goal == "Run the hero skill."

def test_resolve_auto_trigger(tmp_path):
    (tmp_path / "hero.md").write_text("name: hero\nauto: true\ntriggers: hero\n\nx", encoding="utf-8")
    goal, skill, via_auto = commands.resolve_skill("show the hero rail", skills_dir=tmp_path)
    assert skill == "hero" and via_auto is True and goal == "show the hero rail"
```

- [ ] **Step 2: Run it — expect FAIL** (`ModuleNotFoundError`)

Run: `pytest backend/tests/test_commands.py -v`

- [ ] **Step 3: Write `backend/ocd_core/commands.py`**

Encodes the slash set + the explicit-then-auto resolution from app.py's live `on_message` (2566), decoupled from Chainlit and uploaded `elements` (filenames passed as plain strings).

```python
"""UI-agnostic slash-command parsing + skill resolution (salvaged from app.py
on_message, §6). Returns intents/text — never touches a UI session."""
from dataclasses import dataclass
from pathlib import Path

from . import skills as _skills

# command name -> set of accepted prefixes (lowercased)
_EXACT = {
    "projects": {"/projects"},
    "skills": {"/skills"},
    "reload_skills": {"/reload-skills"},
    "lint_knowledge": {"/lint-knowledge"},
}
_EXACT_MULTI = {"refresh_catalog": {"/refresh-catalog", "/rebuild-catalog"}}
_PREFIX = {  # command name -> prefix that takes a trailing argument
    "project": "/project ",
    "set_instructions": "/set-instructions",
    "learn_finding": "/learn-finding",
}


@dataclass
class Command:
    name: str | None      # None => not a command (plain message)
    arg: str              # argument text (or the original text when name is None)
    raw: str


def parse(text: str) -> Command:
    raw = (text or "").strip()
    low = raw.lower()
    for name, prefixes in {**_EXACT, **_EXACT_MULTI}.items():
        if low in prefixes:
            return Command(name=name, arg="", raw=raw)
    for name, prefix in _PREFIX.items():
        if low == prefix.strip() or low.startswith(prefix):
            return Command(name=name, arg=raw[len(prefix):].strip(), raw=raw)
    return Command(name=None, arg=raw, raw=raw)


def resolve_skill(text: str, skills_dir: Path | None = None,
                  filenames: list[str] | None = None) -> tuple[str, str, bool]:
    """Returns (cleaned_goal, skill_name|'' , via_auto). Mirrors app.py 2566:
    explicit `/skill-name [args]` (word-exact) wins; else auto-trigger."""
    goal = (text or "").strip()
    available = _skills.list_skills(skills_dir)
    if goal.startswith("/"):
        low = goal.lower()
        for s in available:
            cmd = f"/{s['name']}".lower()
            if low == cmd or low.startswith(cmd + " "):
                rest = goal[len(cmd):].strip()
                return (rest or f"Run the {s['name']} skill.", s["name"], False)
    name = _skills.matching_skill(goal, skills_dir, filenames=filenames)
    return (goal, name, bool(name))
```

- [ ] **Step 4: Run it — expect PASS**

Run: `pytest backend/tests/test_commands.py -v`

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "feat(core): UI-agnostic slash-command + skill resolver in ocd_core.commands (§6)"
```

---

## Task 7: move data domain (projects, conversations, knowledge) into `ocd_core`

These are filesystem-backed and highly testable. Move them out of `legacy_frontend/core.py` and re-export. (DB migration is a **later phase** — this is a faithful file-based move.)

**Files:**
- Create: `backend/ocd_core/projects.py`, `conversations.py`, `knowledge.py`
- Create: `backend/tests/test_projects.py`, `test_conversations.py`
- Modify: `legacy_frontend/core.py` (re-export the moved names)

- [ ] **Step 1: Write failing tests** (`backend/tests/test_projects.py`)

```python
import importlib, pytest

@pytest.fixture
def core(monkeypatch, tmp_path):
    monkeypatch.setenv("OCD_DATA_DIR", str(tmp_path))
    import ocd_core.config as c; importlib.reload(c)
    import ocd_core.projects as p; importlib.reload(p)
    return p

def test_create_and_get_project(core):
    meta = core.create_project("Al Jazeera 360")
    assert meta["id"] == "al-jazeera-360"
    assert core.get_project(meta["id"])["name"] == "Al Jazeera 360"
    assert any(p["id"] == meta["id"] for p in core.list_projects())

def test_duplicate_name_gets_unique_id(core):
    a = core.create_project("Dup"); b = core.create_project("Dup")
    assert a["id"] != b["id"]

def test_delete_project(core):
    meta = core.create_project("Temp")
    assert core.delete_project(meta["id"]) is True
    assert core.get_project(meta["id"]) is None
```

(`backend/tests/test_conversations.py`)

```python
import importlib, pytest

@pytest.fixture
def mods(monkeypatch, tmp_path):
    monkeypatch.setenv("OCD_DATA_DIR", str(tmp_path))
    import ocd_core.config as c; importlib.reload(c)
    import ocd_core.projects as p; importlib.reload(p)
    import ocd_core.conversations as cv; importlib.reload(cv)
    return p, cv

def test_create_save_get_conversation(mods):
    p, cv = mods
    proj = p.create_project("P")
    conv = cv.create_conversation(proj["id"], "first message about hero rails")
    cv.save_conversation(proj["id"], conv["id"],
                         [{"role": "user", "content": "hi"}], title="T")
    got = cv.get_conversation(proj["id"], conv["id"])
    assert got["title"] == "T" and got["messages"][0]["content"] == "hi"

def test_pin_and_list(mods):
    p, cv = mods
    proj = p.create_project("P")
    conv = cv.create_conversation(proj["id"], "msg")
    cv.set_conversation_pinned(proj["id"], conv["id"], True)
    assert cv.list_conversations(proj["id"])[0]["pinned"] is True
```

- [ ] **Step 2: Run — expect FAIL** (`ModuleNotFoundError`)

Run: `pytest backend/tests/test_projects.py backend/tests/test_conversations.py -v`

- [ ] **Step 3: Move the code.** Cut these functions from `legacy_frontend/core.py` into the new modules verbatim (harvested line ranges in parens), fixing imports to `from . import config, util` and `from .observability import observe`:
  - `projects.py`: `_load_registry` (142), `_save_registry` (151), `list_projects` (157), `get_project` (161), `create_project` (165), `delete_project` (185), `get_project_instructions` (202), `save_project_instructions` (207), `get_project_memory` (~362), `save_project_memory` (~371), `get_project_allowlist` (123), `project_capacity` (542), `project_card_view` (614). Uses `config.PROJECTS_DIR`, `util.slugify`.
  - `conversations.py`: `_conv_dir` (380), `_conv_path` (389), `_conv_title_from` (398), `_write_conversation` (407), `create_conversation` (416), `get_conversation` (425), `save_conversation` (434), `set_conversation_title` (443), `set_conversation_pinned` (452), `move_conversation` (461), `delete_conversation` (470), `list_conversations` (479), `list_all_conversations` (488), `migrate_legacy_chat_history` (515). Uses `config.CONV_MAX_MESSAGES`.
  - `knowledge.py`: `_file_meta` (524), `list_project_files` (533), `save_uploaded_file` (551), `extract_text_from_file` (569), `ingest_file_to_kb` (578), `list_all_files` (497), `get_project_kb_collection` (119), `search_project_kb` (704). Uses `util.chunk_id`, the Chroma accessor (moved in Task 8) — import lazily to avoid a cycle.

- [ ] **Step 4: Re-export from `core.py`** so `legacy_frontend` keeps working:

```python
from ocd_core.projects import (  # noqa: F401
    list_projects, get_project, create_project, delete_project,
    get_project_instructions, save_project_instructions, get_project_memory,
    save_project_memory, get_project_allowlist, project_capacity, project_card_view)
from ocd_core.conversations import (  # noqa: F401
    create_conversation, get_conversation, save_conversation,
    set_conversation_title, set_conversation_pinned, move_conversation,
    delete_conversation, list_conversations, list_all_conversations,
    migrate_legacy_chat_history)
from ocd_core.knowledge import (  # noqa: F401
    list_project_files, save_uploaded_file, extract_text_from_file,
    ingest_file_to_kb, list_all_files, get_project_kb_collection, search_project_kb)
```

- [ ] **Step 5: Run — expect PASS**

Run: `pytest backend/tests/test_projects.py backend/tests/test_conversations.py -v`

- [ ] **Step 6: Sanity (Appendix A) + commit**

```bash
git add -A && git commit -m "refactor(core): move projects/conversations/knowledge into ocd_core"
```

---

## Task 8: move BigQuery + schema-catalog + LLM into `ocd_core` (incl. SALVAGE 4)

I/O-heavy. Move the clients and SQL gateway, fold in the eager catalog rebuild (concern 4). Tests use mocked clients + the real guard wiring (no live BigQuery).

**Files:**
- Create: `backend/ocd_core/bigquery.py`, `schema_catalog.py`, `llm.py`
- Create: `backend/tests/test_execute_sql_guard.py`
- Modify: `legacy_frontend/core.py` (re-export)

- [ ] **Step 1: Write the failing test** (`backend/tests/test_execute_sql_guard.py`)

Characterization of the guard path in `execute_sql` without hitting BigQuery — inject a fake client/dry-run.

```python
import importlib, pytest

@pytest.fixture
def bq(monkeypatch, tmp_path):
    monkeypatch.setenv("OCD_DATA_DIR", str(tmp_path))
    import ocd_core.config as c; importlib.reload(c)
    import ocd_core.bigquery as b; importlib.reload(b)
    return b

def test_mutation_is_blocked_before_any_io(bq, monkeypatch):
    called = {"dry": False}
    monkeypatch.setattr(bq, "_dry_run", lambda sql: called.__setitem__("dry", True))
    out = bq.execute_sql("DELETE FROM analytics.events WHERE 1=1")
    assert out["ok"] is False and "read-only" in out["error"].lower()
    assert called["dry"] is False   # rejected before dry-run

def test_banned_alias_is_blocked(bq):
    out = bq.execute_sql("SELECT 1 AS rows FROM analytics.events")
    assert out["ok"] is False and "alias" in out["error"].lower()
```

- [ ] **Step 2: Run — expect FAIL** (`ModuleNotFoundError`)

Run: `pytest backend/tests/test_execute_sql_guard.py -v`

- [ ] **Step 3: Move the code.** From `legacy_frontend/core.py`:
  - `bigquery.py`: `get_bq_client` (632), `_dry_run` (731), `execute_sql` (740), `fmt_bytes` shim → use `util.fmt_bytes`. Import guards: `from .sql_guard import is_mutation, tables_out_of_scope, check_banned_aliases, tables_off_allowlist`. Wire `tables_off_allowlist` + `observability.check_rate_limit`/`audit` to replace the Chainlit `cl.user_session` reads (callers now pass `active_project`/`user_id` explicitly — keep current default params).
  - `schema_catalog.py`: `_schema_catalog` (650), `_kb_documents` (659), `_flatten_fields`→`util.flatten_fields`, `_catalog_version_matches` (677), `_build_catalog_sync` (686), `ensure_catalog` (695), `search_schema` (713), plus `_write_catalog_version` and the eager-rebuild logic (salvage 4). `_get_chroma` (111) moves here (or a small `chroma.py`); `knowledge.py` imports it lazily.
  - `llm.py`: `get_llm_client` (641), `get_settings`/`save_settings` (77/94) → or keep settings in a small `settings.py`; for this phase put `get_llm_client` in `llm.py` and leave settings in `core.py` re-exporting.

- [ ] **Step 4: Re-export from `core.py`**

```python
from ocd_core.bigquery import get_bq_client, execute_sql  # noqa: F401
from ocd_core.schema_catalog import (  # noqa: F401
    ensure_catalog, search_schema, rebuild_catalog, _get_chroma)
from ocd_core.llm import get_llm_client  # noqa: F401
from ocd_core.util import fmt_bytes  # noqa: F401
```

- [ ] **Step 5: Run — expect PASS**

Run: `pytest backend/tests/test_execute_sql_guard.py -v`
Expected: PASS (guard rejects before I/O; banned alias caught).

- [ ] **Step 6: Sanity (Appendix A) + commit**

```bash
git add -A && git commit -m "refactor(core): move bigquery/schema_catalog/llm into ocd_core (+catalog rebuild #4)"
```

---

## Task 9: move the agent loop + integrations + MCP registry into `ocd_core`

Move the remaining domain: `agent.py` (the `run_turn` loop), `integrations.py` (plugins/connectors/mcp/web), `mcp_registry.py`. Behavior is preserved exactly; the Analytics-specific system prompt moves as-is (parameterizing it is a documented later refinement).

**Files:**
- Create: `backend/ocd_core/agent.py`
- Create: `backend/ocd_core/integrations/{__init__.py,plugins.py,connectors.py,mcp_registry.py,web.py}`
- Move: `legacy_frontend/mcp_registry.py` → `backend/ocd_core/integrations/mcp_registry.py`
- Move: `tests/test_mcp_registry.py` → `backend/tests/test_mcp_registry.py`
- Create: `backend/tests/test_agent_import.py`
- Modify: `legacy_frontend/{agent,integrations,mcp_registry}.py` → re-export shims

- [ ] **Step 1: Write the failing test** (`backend/tests/test_agent_import.py`)

```python
def test_agent_and_integrations_importable():
    from ocd_core import agent
    from ocd_core.integrations import plugins, connectors, web, mcp_registry
    import inspect
    assert inspect.isasyncgenfunction(agent.run_turn)
    # the real (not docstring) event vocabulary is preserved
    src = inspect.getsource(agent.run_turn)
    assert "think_open" in src and "answer_open" in src
```

Also move `tests/test_mcp_registry.py` → `backend/tests/test_mcp_registry.py` and switch its loader to `from ocd_core.integrations import mcp_registry` (drop `spec_from_file_location`); update the demo-server path it spawns to the repo's `mcp_servers/demo_server.py` (unchanged location this phase).

- [ ] **Step 2: Run — expect FAIL** (`ModuleNotFoundError`)

Run: `pytest backend/tests/test_agent_import.py backend/tests/test_mcp_registry.py -v`

- [ ] **Step 3: Move the code.**
  - `git mv legacy_frontend/mcp_registry.py backend/ocd_core/integrations/mcp_registry.py` (no body changes; it's standalone).
  - Split `legacy_frontend/integrations.py` by concern into `integrations/{plugins,connectors,web}.py` (+ `__init__.py` re-exporting the public surface: `list_skills` etc. now come from `ocd_core.skills`; `plugin_tools/run_plugin`, `connector_tools/call_connector`, `web_search_with_sources/research_with_sources`, `agent_tools/run_tool`, `web_fetch`, `run_python`, `run_bash`, `text_editor`, `memory_tool`, `SANDBOX_ROOT`, `MEMORY_ROOT`). Fix imports to `from .. import config; from ..skills import ...`.
  - Move `legacy_frontend/agent.py` → `backend/ocd_core/agent.py`. Change `from . import core` → targeted `from . import bigquery, schema_catalog, llm, config, util` and `from . import integrations`. Keep `SYSTEM_PROMPT` as-is (still interpolates `config.PROJECT_ID` + `BANNED_ALIASES`).

- [ ] **Step 4: Re-export shims** — `legacy_frontend/agent.py`, `integrations.py`, `mcp_registry.py` each become one-liners, e.g. `from ocd_core.agent import *  # noqa` and explicit `run_turn` re-export; `from ocd_core.integrations import *`. (state.py/legacy_frontend.py keep importing `from . import agent, integrations` unchanged.)

- [ ] **Step 5: Run — expect PASS**

Run: `pytest backend/tests/test_agent_import.py backend/tests/test_mcp_registry.py -v`

- [ ] **Step 6: Sanity (Appendix A) + commit**

```bash
git add -A && git commit -m "refactor(core): move agent + integrations + mcp_registry into ocd_core"
```

---

## Task 10: collapse the Reflex shims & prove zero duplication

Reduce the `legacy_frontend` domain files to pure re-export shims (or delete them and update `state.py`/`legacy_frontend.py` imports to `from ocd_core import ...`). Confirm no domain logic remains duplicated, the full suite is green, and the Reflex app boots.

**Files:**
- Modify: `legacy_frontend/{core,agent,integrations,mcp_registry}.py`
- Modify (only if shims removed): `legacy_frontend/state.py`, `legacy_frontend.py` import lines
- Create: `backend/tests/test_no_duplication.py`

- [ ] **Step 1: Write the failing/guard test** (`backend/tests/test_no_duplication.py`)

```python
import pathlib

CORE = pathlib.Path("legacy_frontend/core.py")

def test_core_is_a_thin_shim():
    text = CORE.read_text(encoding="utf-8")
    # the heavy domain defs must now live in ocd_core, not here
    for banned in ("def execute_sql", "def _build_catalog_sync", "def create_project"):
        assert banned not in text, f"{banned} still defined in core.py (not consolidated)"

def test_single_definition_of_execute_sql():
    import subprocess, sys
    # exactly one module defines execute_sql: ocd_core.bigquery
    import ocd_core.bigquery as b
    assert b.execute_sql.__module__ == "ocd_core.bigquery"
```

- [ ] **Step 2: Run — expect FAIL** (core.py still holds defs if shims not yet trimmed)

Run: `pytest backend/tests/test_no_duplication.py -v`

- [ ] **Step 3: Trim the shims.** Ensure `core.py` contains only the re-export blocks from Tasks 1–8 (no `def` for moved functions). Same for `agent.py`/`integrations.py`/`mcp_registry.py`. Anything still defined locally must be UI-only; if so, leave it but confirm it's not domain logic.

- [ ] **Step 4: Run the FULL suite — expect PASS**

Run: `pytest backend/tests -v`
Expected: all green.

- [ ] **Step 5: Boot the Reflex app (Appendix A, extended)**

Run: `cd legacy_frontend && python -c "import legacy_frontend.legacy_frontend as ui; print('reflex app import OK')" && cd ..`
Expected: prints `reflex app import OK` with no ImportError.

- [ ] **Step 6: Commit**

```bash
git add -A && git commit -m "refactor(core): reduce Reflex domain modules to ocd_core shims — duplication eliminated"
```

---

## Appendix A: integration sanity check (run after every slice)

Both apps must still resolve their domain imports against the consolidated core. Run from the repo root:

```bash
# 1. consolidated unit tests green
pytest backend/tests -q

# 2. Chainlit app still imports the shared guard (app.py retired later, must work now)
python -c "import ocd_core.sql_guard; print('chainlit core import OK')"

# 3. Reflex app domain layer still imports
cd legacy_frontend && python -c "from legacy_frontend import core, agent, integrations; print('reflex domain import OK')" && cd ..
```

All three must succeed before committing a slice.

## Appendix B: what Phase 1 deliberately does NOT do (guards against scope creep)

- **No FastAPI / HTTP / SSE** — that's Phase 3. The agent stays an in-process async generator.
- **No DB** — projects/conversations stay file-based; the Postgres migration is Phase 2.
- **No directory move of the Reflex app** — it stays at `legacy_frontend/`; relocation to `frontend/` is Phase 4.
- **No deletion of `app.py`** — Chainlit is retired in Phase 5, after parity is proven.
- **No fixing the allowlist substring wart, no parameterizing the Analytics system prompt** — ported faithfully; flagged for a later hardening pass.
- **No `pydantic-settings`, `runtime/` move, `backend/content/` move, `.claude/` layer** — Phase 6.

## Self-review

- **Spec coverage (§10.1 + §6):** config (T1), pure-helper de-dup (T2), salvage #1 rate-limit + #3 audit (T3), #2 allowlist (T4), skill consolidation (T5), #5 slash-command + skill-trigger → UI-agnostic core (T6), data domain move (T7), bigquery/llm + #4 catalog (T8), agent+integrations+mcp move (T9), duplication eliminated + Reflex-as-consumer (T10). Backend package + real-import tests addresses audit #5 for the moved tests (T0, T9). ✓
- **Placeholder scan:** two intentional `...` bodies in T2 are flagged with an explicit "port the existing body from <file>:<line>" instruction + a follow-up test requirement — not silent TODOs. No other placeholders.
- **Type/name consistency:** `tables_off_allowlist` (T4) used in T8; `RateLimiter.check`/`check_rate_limit` (T3) used in T8; `ocd_core.skills.matching_skill`/`list_skills` (T5) used by `commands.resolve_skill` (T6); `config.*` names (T1) used throughout. Consistent.
