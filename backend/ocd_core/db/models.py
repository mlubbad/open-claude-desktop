"""SQLModel tables for durable, workspace-scoped product persistence."""
from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import JSON, CheckConstraint, Column, Index, UniqueConstraint
from sqlmodel import Field, SQLModel


def utcnow() -> datetime:
    return datetime.now(UTC)


# Multi-user seams (Phase 1b): nullable ownership columns present from day one so a
# future self-hosted server mode can scope rows per user/workspace WITHOUT a
# cross-cutting retrofit. They stay NULL and unused in local-first single-user mode.
class Project(SQLModel, table=True):
    id: str = Field(primary_key=True)              # the slug
    name: str
    description: str = ""                           # shown on the project card
    instructions: str = ""
    memory: str = ""
    pinned: bool = False                            # pinned to the sidebar
    archived: bool = False                          # hidden from the default list
    allowlist: list = Field(default_factory=list, sa_column=Column(JSON))
    owner_id: str | None = Field(default=None, index=True)
    workspace_id: str | None = Field(default=None, index=True)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class Conversation(SQLModel, table=True):
    id: str = Field(primary_key=True)              # 12-hex id
    project_id: str = Field(index=True)            # soft ref ("general" or a slug)
    title: str
    pinned: bool = False
    transcript: list = Field(default_factory=list, sa_column=Column(JSON))
    # Branching: a conversation forked from another carries its parent's id and the
    # message index it was forked AT (its transcript is a copy of the parent up to and
    # including that message). Both NULL for a normal (root) conversation.
    parent_id: str | None = Field(default=None, index=True)
    fork_index: int | None = None
    # Optimistic-concurrency version: bumped on every save. A client that saves with a
    # stale expected_version (another window/client wrote in between) is rejected rather
    # than silently clobbering the newer transcript.
    version: int = Field(default=1)
    owner_id: str | None = Field(default=None, index=True)
    workspace_id: str | None = Field(default=None, index=True)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class Job(SQLModel, table=True):
    """A durable background job (hosted-SaaS slice 4c). Rows exist only when the durable
    queue backend is selected (OCD_JOB_QUEUE=sql); the default in-process queue never
    touches this table. `payload` is the serializable spec a runner rebuilds the work
    from; `dedup_key` is UNIQUE so two nodes racing to enqueue one occurrence make one
    job; `status`/`worker_id`/`lease_expires_at` drive atomic claim + lease reclaim."""

    id: str = Field(primary_key=True)                 # uuid hex
    kind: str = Field(index=True)                      # runner key, e.g. "run_schedule"
    payload: dict = Field(default_factory=dict, sa_column=Column(JSON))
    status: str = Field(default="queued", index=True)  # queued | running | done | failed
    dedup_key: str | None = Field(default=None, unique=True)
    run_at: datetime = Field(default_factory=utcnow, index=True)  # not-before time
    attempts: int = Field(default=0)
    max_attempts: int = Field(default=3)
    worker_id: str | None = Field(default=None)
    # Random fencing token issued on every claim. Worker ids may be reused after a
    # crash; the token prevents a stale attempt from completing a later claim.
    lease_token: str | None = Field(default=None, index=True)
    lease_expires_at: datetime | None = Field(default=None)
    last_error: str | None = Field(default=None)
    workspace_id: str | None = Field(default=None, index=True)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class Workspace(SQLModel, table=True):
    id: str = Field(primary_key=True)
    name: str
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class WorkspaceMembership(SQLModel, table=True):
    __table_args__ = (
        CheckConstraint("role IN ('viewer','member','admin','owner')", name="ck_membership_role"),
        Index("ix_membership_user_workspace", "user_id", "workspace_id"),
    )

    workspace_id: str = Field(foreign_key="workspace.id", primary_key=True)
    user_id: str = Field(primary_key=True)
    role: str = Field(default="viewer")
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class CoworkTaskRecord(SQLModel, table=True):
    __table_args__ = (
        UniqueConstraint("workspace_id", "record_id", name="uq_cowork_workspace_record"),
        Index("ix_cowork_workspace_status_updated", "workspace_id", "status", "updated_at"),
    )

    key: str = Field(primary_key=True)
    record_id: str = Field(index=True)
    workspace_id: str = Field(foreign_key="workspace.id", index=True)
    owner_id: str | None = Field(default=None, index=True)
    status: str = Field(default="running")
    title: str = ""
    payload: dict = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class ScheduledTaskRecord(SQLModel, table=True):
    __table_args__ = (
        UniqueConstraint("workspace_id", "record_id", name="uq_schedule_workspace_record"),
        Index("ix_schedule_workspace_enabled_updated", "workspace_id", "enabled", "updated_at"),
    )

    key: str = Field(primary_key=True)
    record_id: str = Field(index=True)
    workspace_id: str = Field(foreign_key="workspace.id", index=True)
    owner_id: str | None = Field(default=None, index=True)
    enabled: bool = True
    payload: dict = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class IntegrationRecord(SQLModel, table=True):
    __table_args__ = (
        UniqueConstraint(
            "workspace_id", "kind", "record_id", name="uq_integration_workspace_kind_record"
        ),
        Index("ix_integration_workspace_kind_updated", "workspace_id", "kind", "updated_at"),
    )

    key: str = Field(primary_key=True)
    record_id: str = Field(index=True)
    workspace_id: str = Field(foreign_key="workspace.id", index=True)
    owner_id: str | None = Field(default=None, index=True)
    kind: str = Field(index=True)
    name: str = ""
    config: dict = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class ApprovalRecord(SQLModel, table=True):
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending','approved','declined','expired')",
            name="ck_approval_status",
        ),
        UniqueConstraint("workspace_id", "record_id", name="uq_approval_workspace_record"),
        Index("ix_approval_workspace_status_updated", "workspace_id", "status", "updated_at"),
    )

    key: str = Field(primary_key=True)
    record_id: str = Field(index=True)
    workspace_id: str = Field(foreign_key="workspace.id", index=True)
    owner_id: str | None = Field(default=None, index=True)
    status: str = Field(default="pending")
    payload: dict = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
