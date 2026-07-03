"""add nullable owner_id/workspace_id seams to project + conversation

Phase 1b: multi-user ownership columns present from day one (NULL in local mode)
so a future server mode scopes rows per user/workspace without a schema retrofit.

Revision ID: b1c2d3e4f5a6
Revises: 803915bc18bc
Create Date: 2026-07-03 00:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'b1c2d3e4f5a6'
down_revision: str | Sequence[str] | None = '803915bc18bc'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_STR = sqlmodel.sql.sqltypes.AutoString()


def upgrade() -> None:
    for table in ("project", "conversation"):
        op.add_column(table, sa.Column('owner_id', _STR, nullable=True))
        op.add_column(table, sa.Column('workspace_id', _STR, nullable=True))
        op.create_index(op.f(f'ix_{table}_owner_id'), table, ['owner_id'], unique=False)
        op.create_index(op.f(f'ix_{table}_workspace_id'), table, ['workspace_id'], unique=False)


def downgrade() -> None:
    for table in ("project", "conversation"):
        op.drop_index(op.f(f'ix_{table}_workspace_id'), table_name=table)
        op.drop_index(op.f(f'ix_{table}_owner_id'), table_name=table)
        op.drop_column(table, 'workspace_id')
        op.drop_column(table, 'owner_id')
