"""SQLModel tables for ocd_core persistence (Phase 2): Project, Conversation."""
from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import JSON, Column
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
    owner_id: str | None = Field(default=None, index=True)
    workspace_id: str | None = Field(default=None, index=True)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
