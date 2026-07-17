"""workspace-scoped control-plane tables

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
"""
from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel
from alembic import op

revision: str = "e5f6a7b8c9d0"
down_revision: str | Sequence[str] | None = "d4e5f6a7b8c9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

S = sqlmodel.sql.sqltypes.AutoString


def _record_table(name: str, *, approval=False, schedule=False, integration=False) -> None:
    columns = [
        sa.Column("key", S(), primary_key=True),
        sa.Column("record_id", S(), nullable=False),
        sa.Column("workspace_id", S(), sa.ForeignKey("workspace.id", ondelete="CASCADE"), nullable=False),
        sa.Column("owner_id", S(), nullable=True),
    ]
    if integration:
        columns += [sa.Column("kind", S(), nullable=False), sa.Column("name", S(), nullable=False),
                    sa.Column("config", sa.JSON(), nullable=False)]
    else:
        if approval:
            columns.append(sa.Column("status", S(), nullable=False))
        elif schedule:
            columns.append(sa.Column("enabled", sa.Boolean(), nullable=False))
        else:
            columns += [sa.Column("status", S(), nullable=False), sa.Column("title", S(), nullable=False)]
        columns.append(sa.Column("payload", sa.JSON(), nullable=False))
    columns += [sa.Column("created_at", sa.DateTime(), nullable=False),
                sa.Column("updated_at", sa.DateTime(), nullable=False)]
    op.create_table(name, *columns)


def upgrade() -> None:
    op.create_table("workspace", sa.Column("id", S(), primary_key=True),
                    sa.Column("name", S(), nullable=False),
                    sa.Column("created_at", sa.DateTime(), nullable=False),
                    sa.Column("updated_at", sa.DateTime(), nullable=False))
    op.create_table("workspacemembership",
                    sa.Column("workspace_id", S(), sa.ForeignKey("workspace.id", ondelete="CASCADE"), primary_key=True),
                    sa.Column("user_id", S(), primary_key=True), sa.Column("role", S(), nullable=False),
                    sa.Column("created_at", sa.DateTime(), nullable=False),
                    sa.Column("updated_at", sa.DateTime(), nullable=False),
                    sa.CheckConstraint("role IN ('viewer','member','admin','owner')", name="ck_membership_role"))
    _record_table("coworktaskrecord")
    _record_table("scheduledtaskrecord", schedule=True)
    _record_table("integrationrecord", integration=True)
    _record_table("approvalrecord", approval=True)


def downgrade() -> None:
    for table in ("approvalrecord", "integrationrecord", "scheduledtaskrecord", "coworktaskrecord",
                  "workspacemembership", "workspace"):
        op.drop_table(table)
