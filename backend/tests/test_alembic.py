import pathlib

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect


def test_initial_migration_creates_tables(tmp_path, monkeypatch):
    db_file = tmp_path / "alembic.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_file}")
    backend = pathlib.Path("backend")
    cfg = Config(str(backend / "alembic.ini"))
    cfg.set_main_option("script_location", str(backend / "ocd_core" / "db" / "migrations"))
    command.upgrade(cfg, "head")
    insp = inspect(create_engine(f"sqlite:///{db_file}"))
    tables = set(insp.get_table_names())
    assert {"project", "conversation"} <= tables
