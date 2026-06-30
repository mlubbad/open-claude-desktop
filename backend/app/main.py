from __future__ import annotations

import os

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .routes import (
    agent,
    auth,
    conversations,
    health,
    integrations,
    knowledge,
    projects,
    schema,
    settings,
    sql,
)

# Load repo .env for local/dev runs so ZHIPU_API_KEY (and other vars) are present
# without a launcher wrapper. override=False -> the real process env always wins
# (docker-compose env_file / `environment:`, or vars you export), so this is a
# no-op in containers and only fills gaps when running a bare `uvicorn` locally.
load_dotenv()

app = FastAPI(title="ocd backend", version="0.4.0")
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
