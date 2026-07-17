"""SQL persistence for workspace-scoped Cowork, Scheduler, integrations, and approvals."""
from __future__ import annotations

import hashlib

from sqlmodel import select

from . import tenancy
from .db import engine
from .db.models import (
    ApprovalRecord,
    CoworkTaskRecord,
    IntegrationRecord,
    ScheduledTaskRecord,
    Workspace,
    utcnow,
)


def _workspace() -> str:
    return tenancy.current_workspace() if tenancy.enforcing() else tenancy.LOCAL_WORKSPACE


def _key(kind: str, record_id: str, workspace: str | None = None) -> str:
    raw = f"{workspace or _workspace()}\0{kind}\0{record_id}".encode()
    return hashlib.sha256(raw).hexdigest()


def _ensure_workspace(session, workspace: str) -> None:
    if session.get(Workspace, workspace) is None:
        session.add(Workspace(id=workspace, name=workspace))
        session.flush()


def _upsert(model, kind: str, item: dict):
    record_id = str(item.get("id") or "").strip()
    if not record_id:
        raise ValueError("record id is required")
    workspace = _workspace()
    key = _key(kind, record_id, workspace)
    with engine.session() as session:
        _ensure_workspace(session, workspace)
        row = session.get(model, key)
        now = utcnow()
        if row is None:
            common = dict(
                key=key,
                record_id=record_id,
                workspace_id=workspace,
                owner_id=workspace,
                created_at=now,
                updated_at=now,
            )
            if model is CoworkTaskRecord:
                row = model(
                    **common,
                    status=str(item.get("status") or "running"),
                    title=str(item.get("title") or ""),
                    payload=dict(item),
                )
            elif model is ScheduledTaskRecord:
                row = model(
                    **common, enabled=bool(item.get("enabled", True)), payload=dict(item)
                )
            elif model is ApprovalRecord:
                row = model(
                    **common, status=str(item.get("status") or "pending"), payload=dict(item)
                )
            else:
                raise TypeError(model)
        else:
            row.updated_at = now
            row.payload = dict(item)
            if model is CoworkTaskRecord:
                row.status = str(item.get("status") or row.status)
                row.title = str(item.get("title") or row.title)
            elif model is ScheduledTaskRecord:
                row.enabled = bool(item.get("enabled", True))
            elif model is ApprovalRecord:
                row.status = str(item.get("status") or row.status)
        session.add(row)
    return dict(item)


def _list(model) -> list[dict]:
    workspace = _workspace()
    with engine.session() as session:
        rows = session.exec(
            select(model).where(model.workspace_id == workspace).order_by(model.updated_at.desc())
        ).all()
        return [dict(row.payload or {}) for row in rows]


def _delete(model, kind: str, record_id: str) -> bool:
    key = _key(kind, record_id)
    with engine.session() as session:
        row = session.get(model, key)
        if row is None or row.workspace_id != _workspace():
            return False
        session.delete(row)
        return True


def _get(model, kind: str, record_id: str) -> dict | None:
    key = _key(kind, record_id)
    with engine.session() as session:
        row = session.get(model, key)
        if row is None or row.workspace_id != _workspace():
            return None
        return dict(row.payload or {})


def upsert_cowork(item: dict):
    return _upsert(CoworkTaskRecord, "cowork", item)


def list_cowork() -> list[dict]:
    return _list(CoworkTaskRecord)


def get_cowork(record_id: str) -> dict | None:
    return _get(CoworkTaskRecord, "cowork", record_id)


def delete_cowork(record_id: str) -> bool:
    return _delete(CoworkTaskRecord, "cowork", record_id)


def upsert_schedule(item: dict):
    return _upsert(ScheduledTaskRecord, "schedule", item)


def list_schedules() -> list[dict]:
    return _list(ScheduledTaskRecord)


def get_schedule(record_id: str) -> dict | None:
    return _get(ScheduledTaskRecord, "schedule", record_id)


def save_schedules(items: list[dict]) -> None:
    existing = {item["id"] for item in list_schedules()}
    desired = {item["id"] for item in items}
    for record_id in existing - desired:
        delete_schedule(record_id)
    for item in items:
        upsert_schedule(item)


def delete_schedule(record_id: str) -> bool:
    return _delete(ScheduledTaskRecord, "schedule", record_id)


def upsert_approval(item: dict):
    return _upsert(ApprovalRecord, "approval", item)


def list_approvals() -> list[dict]:
    return _list(ApprovalRecord)


def get_approval(record_id: str) -> dict | None:
    return _get(ApprovalRecord, "approval", record_id)


def delete_approval(record_id: str) -> bool:
    return _delete(ApprovalRecord, "approval", record_id)


def load_integrations(kind: str) -> list[dict]:
    workspace = _workspace()
    with engine.session() as session:
        rows = session.exec(
            select(IntegrationRecord).where(
                IntegrationRecord.workspace_id == workspace,
                IntegrationRecord.kind == kind,
            ).order_by(IntegrationRecord.updated_at.desc())
        ).all()
        return [dict(row.config or {}) for row in rows]


def save_integrations(kind: str, items: list[dict]) -> None:
    workspace = _workspace()
    desired = {str(item.get("id") or "").strip(): dict(item) for item in items}
    if "" in desired:
        raise ValueError("integration id is required")
    with engine.session() as session:
        _ensure_workspace(session, workspace)
        existing = session.exec(
            select(IntegrationRecord).where(
                IntegrationRecord.workspace_id == workspace,
                IntegrationRecord.kind == kind,
            )
        ).all()
        for row in existing:
            if row.record_id not in desired:
                session.delete(row)
        for record_id, item in desired.items():
            key = _key(f"integration:{kind}", record_id, workspace)
            row = session.get(IntegrationRecord, key)
            now = utcnow()
            if row is None:
                row = IntegrationRecord(
                    key=key,
                    record_id=record_id,
                    workspace_id=workspace,
                    owner_id=workspace,
                    kind=kind,
                    name=str(item.get("name") or record_id),
                    config=item,
                    created_at=now,
                    updated_at=now,
                )
            else:
                row.name = str(item.get("name") or record_id)
                row.config = item
                row.updated_at = now
            session.add(row)
