from logging.config import fileConfig
from alembic import context
from sqlmodel import SQLModel
import ocd_core.db.models  # noqa: F401  register tables on the metadata
from ocd_core.db.engine import database_url

config = context.config
if config.config_file_name is not None:
    # disable_existing_loggers=False so running a migration in-process (e.g. the
    # test suite) does not silence app loggers like "ocd_agent" created earlier.
    fileConfig(config.config_file_name, disable_existing_loggers=False)
config.set_main_option("sqlalchemy.url", database_url())
target_metadata = SQLModel.metadata


def run_migrations_offline() -> None:
    context.configure(url=database_url(), target_metadata=target_metadata,
                      literal_binds=True, dialect_opts={"paramstyle": "named"})
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    from sqlalchemy import create_engine
    connectable = create_engine(database_url())
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
