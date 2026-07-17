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

from fastapi import Depends, FastAPI, Request  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.middleware.trustedhost import TrustedHostMiddleware  # noqa: E402
from fastapi.responses import JSONResponse  # noqa: E402
from ocd_core import config, launchguard, netguard, scheduler, tenancy  # noqa: E402
from ocd_core.db import engine as db_engine  # noqa: E402

from .deps import scope_workspace  # noqa: E402
from .request_limits import RequestLimitsMiddleware  # noqa: E402
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
    workspaces,
)
from .routes import scheduler as scheduler_routes  # noqa: E402


@asynccontextmanager
async def lifespan(_: FastAPI):
    # Days 1-3 containment: local loopback development remains available, but hosted,
    # public-network and multi-tenant startup is frozen until the P0 launch gates pass.
    launchguard.assert_launch_allowed()
    # C1: fail closed on network exposure. A non-loopback bind with auth disabled
    # (the historical default) is an unauthenticated-RCE surface — refuse to start.
    netguard.assert_safe_binding()
    # Probe the configured database. Strict startup is the default; explicit local-only
    # fallback is reported through the return value.
    fell_back = db_engine.ensure_reachable()
    # Local-first convenience: auto-create the schema for a SQLite DB (the default, or
    # the fallback we just switched to) so a fresh `pip install` + run works with zero
    # migration steps. A healthy Postgres owns its schema via Alembic, so skip it there.
    if fell_back or db_engine.database_url().startswith("sqlite"):
        db_engine.init_db()
    # Background ticker for scheduled ("automation") Cowork tasks. Containment keeps
    # it off unless an operator explicitly sets SCHEDULER_ENABLED=1.
    ticker = None
    if config.SCHEDULER_ENABLED:
        interval = int(os.getenv("SCHEDULER_INTERVAL_SEC", "30"))
        ticker = asyncio.create_task(scheduler.run_loop(interval_seconds=interval))
    # Durable-queue worker (opt-in, OCD_JOB_QUEUE=sql): claim + run enqueued background
    # jobs, reclaiming any a dead node abandoned. A no-op for the default in-process
    # queue (jobs run at enqueue), so this task simply returns immediately then.
    worker = None
    from ocd_core import jobqueue
    if jobqueue.enabled():
        worker = asyncio.create_task(jobqueue.run_worker())
    try:
        yield
    finally:
        for bg in (ticker, worker):
            if bg is not None:
                bg.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await bg
        # Persist Cowork task state (cancel + save any still-running tasks) so a
        # graceful shutdown doesn't lose transcripts.
        from ocd_core import cowork
        with contextlib.suppress(Exception):
            await cowork.manager.aclose()


app = FastAPI(title="ocd backend", version=config.BACKEND_VERSION, lifespan=lifespan,
              # Scope every request to its workspace (no-op unless OCD_MULTI_TENANT is on).
              dependencies=[Depends(scope_workspace)])


@app.exception_handler(tenancy.WorkspaceForbidden)
async def _workspace_forbidden(_: Request, __: tenancy.WorkspaceForbidden) -> JSONResponse:
    # A mutation aimed at another workspace's row. Report 404, never 403 — don't leak that
    # the row exists in a workspace the caller can't see.
    return JSONResponse({"detail": "not found"}, status_code=404)

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

# Default CORS origins: web-dev servers PLUS the packaged Tauri webview origins. A
# built desktop app serves its UI from tauri://localhost (macOS/Linux) or
# http://tauri.localhost (Windows) and fetches the loopback sidecar cross-origin, so
# without these the shipped app's own requests fail CORS preflight. Overridable via
# OCD_CORS_ORIGINS (a hosted deploy sets its real origin).
_origins = os.environ.get(
    "OCD_CORS_ORIGINS",
    "http://localhost:3000,http://localhost:5173,tauri://localhost,http://tauri.localhost",
).split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in _origins if o.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
# Temporary Days 1-3 backstop for direct launches. Compose adds the same controls at
# the Nginx edge, where oversized bodies are rejected before reaching this process.
app.add_middleware(
    RequestLimitsMiddleware,
    max_request_bytes=config.MAX_REQUEST_BYTES,
    max_concurrent=config.MAX_CONCURRENT_REQUESTS,
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
app.include_router(workspaces.router)
