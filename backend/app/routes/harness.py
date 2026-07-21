"""Harness routes: code-workspace CRUD/recents/rules.

NOTE (deviation from the plan): the plan specifies a bare "/workspaces" prefix, but
app/routes/workspaces.py already owns "/workspaces" for the unrelated TENANCY concept
(workspace membership). Mixing the harness folder-workspace into that namespace is
confusing and a latent collision risk, so these routes live under "/harness/workspaces"
instead -- see the module docstring in tests/test_harness_routes.py for the full
rationale.
"""
from __future__ import annotations

import re
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from ocd_core import config, workspace_registry
from ocd_core.harness.checkpoints import CheckpointStore
from pydantic import BaseModel

from ..deps import current_user

router = APIRouter(prefix="/harness/workspaces")

# A rule is "name" or "name(matcher)" (or the bare wildcard "*"), name lowercase
# snake_case -- matches ocd_core.harness.rules._parse's own shape. Rejects garbage
# early (422) instead of silently storing an unparseable rule that never matches.
_RULE_PATTERN = re.compile(r"^([a-z_][a-z0-9_]*|\*)(\(.*\))?$")


class WorkspaceCreate(BaseModel):
    root: str


class RulesBody(BaseModel):
    allow: list[str] = []
    deny: list[str] = []
    ask: list[str] = []


class RestoreBody(BaseModel):
    # "conversation" restore is deferred (desktop-side, out of scope here) -- NOT
    # implemented by CheckpointStore.restore(), so it is rejected at the schema level
    # rather than silently no-op'ing.
    what: Literal["files", "both"] = "files"


def _validate_rules(body: RulesBody) -> None:
    for rule in (*body.allow, *body.deny, *body.ask):
        if not _RULE_PATTERN.match(rule):
            raise HTTPException(422, f"invalid rule: {rule!r}")


@router.post("")
def create_workspace(body: WorkspaceCreate, user: str = Depends(current_user)) -> dict:
    try:
        return workspace_registry.register(body.root)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@router.get("")
def list_workspaces(user: str = Depends(current_user)) -> list[dict]:
    return workspace_registry.list_recents()


@router.get("/{wid}")
def get_workspace(wid: str, user: str = Depends(current_user)) -> dict:
    ws = workspace_registry.get(wid)
    if not ws:
        raise HTTPException(404, "unknown workspace")
    return ws


@router.put("/{wid}/rules")
def set_rules(wid: str, body: RulesBody, user: str = Depends(current_user)) -> dict:
    if not workspace_registry.get(wid):
        raise HTTPException(404, "unknown workspace")
    _validate_rules(body)
    workspace_registry.set_rules(wid, body.model_dump())
    return {"ok": True}


def _store(turn_id: str) -> CheckpointStore:
    # Turn-agnostic root; turn_id is the checkpoint_id (matches Task 14 wiring:
    # agent.py's run_turn constructs the SAME CheckpointStore(config.REPO_ROOT /
    # "checkpoints") and snapshots under the turn's own id).
    return CheckpointStore(config.REPO_ROOT / "checkpoints")


@router.get("/{wid}/checkpoints/{turn_id}")
def list_checkpoints(wid: str, turn_id: str, user: str = Depends(current_user)) -> list[dict]:
    ws = workspace_registry.get(wid)
    if not ws:
        raise HTTPException(404, "unknown workspace")
    store = _store(turn_id)
    # A checkpoint that exists but was produced by a DIFFERENT workspace is reported
    # the same as one that never existed -- "nothing to show", not a 404, and never
    # its contents (see restore_checkpoint for why this must be 404 there instead).
    if not store.owned_by(turn_id, ws["root"]):
        return []
    return store.list(turn_id)


@router.post("/{wid}/checkpoints/{turn_id}/restore")
def restore_checkpoint(wid: str, turn_id: str, body: RestoreBody,
                       user: str = Depends(current_user)) -> dict:
    ws = workspace_registry.get(wid)
    if not ws:
        raise HTTPException(404, "unknown workspace")
    store = _store(turn_id)
    # CRITICAL: a checkpoint produced by a different workspace must never be
    # restorable here (turn_id is not workspace-unique) -- 404 rather than a silent
    # no-op so a caller can tell "wrong workspace" from "nothing changed".
    if not store.owned_by(turn_id, ws["root"]):
        raise HTTPException(404, "no such checkpoint for this workspace")
    n = store.restore(turn_id, ws["root"], what=body.what)
    return {"ok": True, "restored": n}
