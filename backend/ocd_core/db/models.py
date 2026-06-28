"""SQLModel tables for ocd_core persistence (Phase 2): Project, Conversation."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import JSON, Column
from sqlmodel import Field, SQLModel


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Project(SQLModel, table=True):
    id: str = Field(primary_key=True)              # the slug
    name: str
    instructions: str = ""
    memory: str = ""
    allowlist: list = Field(default_factory=list, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class Conversation(SQLModel, table=True):
    id: str = Field(primary_key=True)              # 12-hex id
    project_id: str = Field(index=True)            # soft ref ("general" or a slug)
    title: str
    pinned: bool = False
    transcript: list = Field(default_factory=list, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
