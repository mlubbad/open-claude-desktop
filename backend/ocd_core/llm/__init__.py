"""Model-agnostic LLM layer.

Public surface (back-compat + new):
  * get_llm_client()            — the default provider's OpenAI-compatible client
  * get_client(provider_id)     — a specific provider's client
  * get_client_for_model(model) — resolve (client, bare_model) from 'provider/model'
  * reasoning_of(delta)         — normalize reasoning/thinking deltas across providers
  * providers / keys / catalog  — registry, BYOK key storage, capability lookup
"""
from __future__ import annotations

from . import catalog, keys, providers
from .client import (
    LLMConfigError,
    get_client,
    get_client_for_model,
    get_llm_client,
    list_provider_models,
    probe_provider,
    reasoning_of,
    reset_clients,
    resolve_turn_client,
    split_model,
)
from .providers import Provider, default_provider_id, get_provider, list_providers

__all__ = [
    "LLMConfigError",
    "Provider",
    "catalog",
    "default_provider_id",
    "get_client",
    "get_client_for_model",
    "get_llm_client",
    "get_provider",
    "keys",
    "list_provider_models",
    "list_providers",
    "probe_provider",
    "providers",
    "reasoning_of",
    "reset_clients",
    "resolve_turn_client",
    "split_model",
]
