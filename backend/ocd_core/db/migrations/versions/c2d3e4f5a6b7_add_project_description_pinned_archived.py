"""add description/pinned/archived to project (Claude-Desktop-style Projects)

Adds the card description plus the pinned/archived flags the Projects grid and
sidebar use. Local SQLite installs also get these via engine.ensure_columns(); this
migration is the Postgres/prod path.

Revision ID: c2d3e4f5a6b7
Revises: b1c2d3e4f5a6
Create Date: 2026-07-08 00:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'c2d3e4f5a6b7'
down_revision: str | Sequence[str] | None = 'b1c2d3e4f5a6'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_STR = sqlmodel.sql.sqltypes.AutoString()


def upgrade() -> None:
    op.add_column('project', sa.Column('description', _STR, nullable=False,
                                       server_default=''))
    op.add_column('project', sa.Column('pinned', sa.Boolean(), nullable=False,
                                       server_default=sa.false()))
    op.add_column('project', sa.Column('archived', sa.Boolean(), nullable=False,
                                       server_default=sa.false()))


def downgrade() -> None:
    op.drop_column('project', 'archived')
    op.drop_column('project', 'pinned')
    op.drop_column('project', 'description')
