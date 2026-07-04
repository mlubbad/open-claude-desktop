"""BYOK model-provider management (Phase 1).

Lists the available model providers and lets the user store/clear their own API
key per provider. Keys are written to the OS keychain / encrypted store via
ocd_core.secrets and are NEVER returned by any endpoint — only a `has_key` flag.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from ocd_core import llm
from ocd_core.llm import keys as llm_keys
from pydantic import BaseModel

from ..deps import current_user

router = APIRouter()


class KeyBody(BaseModel):
    key: str


def _provider_view(p) -> dict:
    return {
        "id": p.id,
        "label": p.label,
        "is_local": p.is_local,
        "requires_key": p.requires_key,
        "has_key": llm_keys.has_key(p.id),
        "default_model": p.default_model,
        "models": list(p.models),
        "docs": p.docs,
        "is_default": p.id == llm.default_provider_id(),
    }


@router.get("/providers")
def list_providers(user: str = Depends(current_user)) -> list[dict]:
    return [_provider_view(p) for p in llm.list_providers()]


@router.put("/providers/{provider_id}/key")
def set_provider_key(provider_id: str, body: KeyBody,
                     user: str = Depends(current_user)) -> dict:
    llm_keys.set_api_key(provider_id, body.key)
    llm.reset_clients()  # rebuild the client with the new key on next use
    return {"id": provider_id, "has_key": llm_keys.has_key(provider_id)}


@router.delete("/providers/{provider_id}/key")
def delete_provider_key(provider_id: str, user: str = Depends(current_user)) -> dict:
    llm_keys.delete_api_key(provider_id)
    llm.reset_clients()
    return {"id": provider_id, "has_key": llm_keys.has_key(provider_id)}


@router.post("/providers/{provider_id}/test")
def test_provider(provider_id: str, user: str = Depends(current_user)) -> dict:
    """Verify a BYOK provider is reachable and the key works (a 1-token completion)."""
    ok, detail = llm.probe_provider(provider_id)
    return {"id": provider_id, "ok": ok, "detail": detail}


@router.get("/providers/{provider_id}/models")
def provider_models(provider_id: str, user: str = Depends(current_user)) -> dict:
    from ocd_core.llm import catalog
    prov = llm.get_provider(provider_id)
    models = list(prov.models) or ([prov.default_model] if prov.default_model else [])
    return {"id": provider_id,
            "models": [{"id": m, "capabilities": vars(catalog.capabilities(m))}
                       for m in models]}
