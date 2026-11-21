"""BYOK — provider API keys in the OS keychain, never plaintext (Phase 1 + C3).

Keys resolve in priority order:
  1. the secret store (``ocd_core.secrets`` — OS keychain / encrypted file), then
  2. the provider's documented env var (e.g. OPENAI_API_KEY), then
  3. the generic LLM_API_KEY env var (for a custom default provider).

Storing a key writes ONLY to the secret store. Local runtimes (Ollama, vLLM, …)
don't require a key.
"""
from __future__ import annotations

import os

from .providers import CUSTOM_KEY_ENV, get_provider


def _storage_key(provider_id: str) -> str:
    return f"provider:{provider_id}:api_key"


def get_api_key(provider_id: str | None = None) -> str | None:
    """Resolve the API key for a provider (store, then env fallbacks)."""
    prov = get_provider(provider_id)
    from .. import secrets
    stored = secrets.get_secret_store().get(_storage_key(prov.id))
    if stored:
        return stored
    if prov.key_env and os.getenv(prov.key_env):
        return os.getenv(prov.key_env)
    if os.getenv(CUSTOM_KEY_ENV):
        return os.getenv(CUSTOM_KEY_ENV)
    return None


def set_api_key(provider_id: str, key: str) -> None:
    from .. import secrets
    secrets.get_secret_store().set(_storage_key(provider_id), (key or "").strip())


def delete_api_key(provider_id: str) -> None:
    from .. import secrets
    secrets.get_secret_store().delete(_storage_key(provider_id))


def has_key(provider_id: str | None = None) -> bool:
    """Whether a key/token is set — or, for key-free providers, that none is needed.

    For a required-key provider this doubles as "usable". A key-OPTIONAL provider
    (e.g. Vertex AI: ADC by default, pasted token as an override) stays usable
    without one, so here we report the actual override presence — it drives the
    settings badge ("token set" vs the ADC default), not any gating."""
    prov = get_provider(provider_id)
    if prov.requires_key or prov.key_optional:
        return bool(get_api_key(prov.id))
    return True


def has_key_map(provider_ids: list[str]) -> dict[str, bool]:
    """Resolve ``has_key`` for many providers, reading the secret store CONCURRENTLY.

    Each OS-keychain read is a slow IPC round-trip; done serially (as GET /providers
    did) ~10 hosted providers cost the sum of every read and dominate the settings
    page's load. Reading them in a small thread pool collapses that to roughly one
    read's latency. The current workspace is snapshotted and re-bound inside each
    worker so tenant-scoped secrets still resolve under the right namespace (worker
    threads don't inherit the request's ContextVar automatically)."""
    ids = list(provider_ids)
    if len(ids) <= 1:
        return {pid: has_key(pid) for pid in ids}
    from concurrent.futures import ThreadPoolExecutor

    from .. import tenancy
    ws = tenancy.current_workspace()

    def _one(pid: str) -> bool:
        with tenancy.use_workspace(ws):
            return has_key(pid)

    with ThreadPoolExecutor(max_workers=min(8, len(ids))) as ex:
        return dict(zip(ids, ex.map(_one, ids), strict=True))
