from __future__ import annotations

import os

from dotenv import load_dotenv

# Load repo .env BEFORE importing modules that read env at import time (notably
# ocd_core.config.PROJECT_ID, pulled in via the route imports below). override=
# False -> real process env wins (docker-compose env_file / `environment:` /
# exported vars), so this is a no-op in containers and only fills gaps locally.
load_dotenv()

import asyncio  # noqa: E402
import contextlib  # noqa: E402
from contextlib import asynccontextmanager  # noqa: E402

from fastapi import FastAPI  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from ocd_core import netguard, scheduler  # noqa: E402

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


app = FastAPI(title="ocd backend", version="0.4.0", lifespan=lifespan)
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
app.include_router(code.router)
app.include_router(cowork.router)
app.include_router(scheduler_routes.router)
