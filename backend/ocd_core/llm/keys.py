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
    """True when a provider is usable: it has a key, or it needs none (local)."""
    prov = get_provider(provider_id)
    if not prov.requires_key:
        return True
    return bool(get_api_key(prov.id))
