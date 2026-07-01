"""add conversation.tools

Revision ID: a1b2c3d4e5f6
Revises: 803915bc18bc
Create Date: 2026-07-02
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "a1b2c3d4e5f6"
down_revision = "803915bc18bc"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("conversation", sa.Column("tools", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("conversation", "tools")
