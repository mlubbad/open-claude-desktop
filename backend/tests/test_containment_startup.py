import asyncio
from pathlib import Path

import pytest


def test_sqlite_migration_failure_aborts_startup(monkeypatch):
    from app import main

    monkeypatch.setattr(main.launchguard, "assert_launch_allowed", lambda: None)
    monkeypatch.setattr(main.netguard, "assert_safe_binding", lambda: None)
    monkeypatch.setattr(main.db_engine, "ensure_reachable", lambda: None)
    monkeypatch.setattr(main.db_engine, "database_url", lambda: "sqlite://")
    monkeypatch.setattr(
        main.db_engine,
        "init_db",
        lambda: (_ for _ in ()).throw(RuntimeError("migration failed")),
    )

    async def start():
        async with main.lifespan(None):
            pass

    with pytest.raises(RuntimeError, match="migration failed"):
        asyncio.run(start())


def test_container_migration_command_fails_closed():
    dockerfile = (Path(__file__).resolve().parents[2] / "Dockerfile").read_text()
    command = next(line for line in dockerfile.splitlines() if line.startswith("CMD "))
    assert "alembic upgrade head" in command
    assert "|| true" not in command
    assert "set -e" in command
    assert "exec uvicorn" in command
