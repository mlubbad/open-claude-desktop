from __future__ import annotations

import os

from dotenv import load_dotenv

# Load .env BEFORE importing modules that read env at import time (notably
# ocd_core.config.PROJECT_ID, pulled in via the route imports below). override=
# False -> real process env wins (docker-compose env_file / `environment:` /
# exported vars), so this is a no-op in containers and only fills gaps locally.
#
# Looked up in cwd AND at known package-relative locations (backend/.env, repo
# root/.env) so starting uvicorn from any directory finds the same config — a
# cwd-only lookup silently dropped DATABASE_URL and friends when the server was
# launched from the repo root instead of backend/.
load_dotenv()
_here = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(_here, "..", ".env"))          # backend/.env
load_dotenv(os.path.join(_here, "..", "..", ".env"))    # repo-root/.env

import asyncio  # noqa: E402
import contextlib  # noqa: E402
from contextlib import asynccontextmanager  # noqa: E402

from fastapi import FastAPI, Request  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.middleware.trustedhost import TrustedHostMiddleware  # noqa: E402
from fastapi.responses import JSONResponse  # noqa: E402
from ocd_core import config, netguard, scheduler  # noqa: E402
from ocd_core.db import engine as db_engine  # noqa: E402

from .routes import (  # noqa: E402
    agent,
    auth,
    bigquery,
    code,
    conversations,
    cowork,
    health,
    integrations,
    knowledge,
    observability,
    projects,
    providers,
    schema,
    settings,
    sql,
)
from .routes import scheduler as scheduler_routes  # noqa: E402


@asynccontextmanager
async def lifespan(_: FastAPI):
    # C1: fail closed on network exposure. A non-loopback bind with auth disabled
    # (the historical default) is an unauthenticated-RCE surface — refuse to start.
    netguard.assert_safe_binding()
    # Resilience: if the configured (non-SQLite) database is unreachable — a stale
    # DATABASE_URL, a Postgres that isn't running, wrong password — fall back to a
    # local SQLite file so the app keeps working instead of 500-ing on every request.
    fell_back = db_engine.ensure_reachable()
    # Local-first convenience: auto-create the schema for a SQLite DB (the default, or
    # the fallback we just switched to) so a fresh `pip install` + run works with zero
    # migration steps. A healthy Postgres owns its schema via Alembic, so skip it there.
    if fell_back or db_engine.database_url().startswith("sqlite"):
        with contextlib.suppress(Exception):
            db_engine.init_db()
    # Background ticker for scheduled ("automation") Cowork tasks. Disable with
    # SCHEDULER_ENABLED=0 (e.g. in tests / headless one-shots).
    ticker = None
    if os.getenv("SCHEDULER_ENABLED", "1").strip().lower() in ("1", "true", "yes"):
        interval = int(os.getenv("SCHEDULER_INTERVAL_SEC", "30"))
        ticker = asyncio.create_task(scheduler.run_loop(interval_seconds=interval))
    try:
        yield
    finally:
        if ticker is not None:
            ticker.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await ticker
        # Persist Cowork task state (cancel + save any still-running tasks) so a
        # graceful shutdown doesn't lose transcripts.
        from ocd_core import cowork
        with contextlib.suppress(Exception):
            await cowork.manager.aclose()


app = FastAPI(title="ocd backend", version=config.BACKEND_VERSION, lifespan=lifespan)

# Health probes are always reachable (no token, any host) so the shell's readiness
# gate and monitors work before/around auth.
_UNAUTH_PATHS = frozenset({"/healthz", "/readyz"})


# S: per-launch shared-secret token. The desktop shell mints a random token, passes
# it to this sidecar as OCD_API_TOKEN, and hands it to the webview (which sends it as
# X-OCD-Token). When the env is set, every request without the matching token is
# rejected — this is what closes the drive-by-RCE hole: a web page can reach the
# loopback port but cannot read the token, so its requests 401. Unset (dev / plain
# web) → no enforcement, behavior unchanged.
_API_TOKEN = os.environ.get("OCD_API_TOKEN", "").strip()


@app.middleware("http")
async def _require_local_token(request: Request, call_next):
    if _API_TOKEN and request.method != "OPTIONS" and request.url.path not in _UNAUTH_PATHS:
        import hmac
        sent = request.headers.get("x-ocd-token", "")
        if not hmac.compare_digest(sent, _API_TOKEN):
            return JSONResponse({"detail": "missing or invalid local API token"},
                                status_code=401)
    return await call_next(request)


# Host allowlist: reject requests whose Host header isn't in the set (defeats DNS
# rebinding, which otherwise makes an attacker domain resolve to 127.0.0.1 and appear
# same-origin). Defaults to the loopback names the desktop app uses; a non-loopback /
# hosted deploy sets OCD_ALLOWED_HOSTS (comma list; "*" disables the check).
_allowed_hosts = [h.strip() for h in os.environ.get(
    "OCD_ALLOWED_HOSTS", "localhost,127.0.0.1,[::1],testserver").split(",") if h.strip()]
app.add_middleware(TrustedHostMiddleware, allowed_hosts=_allowed_hosts)

_origins = os.environ.get("OCD_CORS_ORIGINS",
                          "http://localhost:3000,http://localhost:5173").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in _origins if o.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(health.router)
app.include_router(auth.router)
app.include_router(agent.router)
app.include_router(projects.router)
app.include_router(conversations.router)
app.include_router(settings.router)
app.include_router(knowledge.router)
app.include_router(schema.router)
app.include_router(integrations.router)
app.include_router(sql.router)
app.include_router(bigquery.router)
app.include_router(providers.router)
app.include_router(observability.router)
app.include_router(code.router)
app.include_router(cowork.router)
app.include_router(scheduler_routes.router)
