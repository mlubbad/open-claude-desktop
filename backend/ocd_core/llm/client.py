"""OpenAI-compatible client factory (Phase 1).

One ``openai.OpenAI(base_url, api_key)`` client per provider drives every backend.
This replaces the hard-coded zhipuai singleton: the call shape the agent loop uses
(``client.chat.completions.create(model=, messages=, tools=, tool_choice=,
stream=, temperature=, max_tokens=)``) is identical, and reasoning deltas
(``delta.reasoning_content``) pass through unchanged because the OpenAI SDK models
allow extra fields.
"""
from __future__ import annotations

import os
import threading

from . import keys
from .providers import CUSTOM_BASE_URL_ENV, default_provider_id, get_provider


class LLMConfigError(RuntimeError):
    """Raised when a provider is selected but not usable (missing key/base_url)."""


_clients: dict[str, object] = {}
_lock = threading.Lock()


def split_model(model: str | None) -> tuple[str | None, str]:
    """Split a ``provider/model`` string. Bare names get provider None (default).

    Only the FIRST slash is treated as a provider separator, and only when the
    prefix is a known provider id — so OpenRouter-style ``vendor/model`` names
    (e.g. ``meta-llama/Llama-3``) are left intact under the default provider.
    """
    m = (model or "").strip()
    if "/" in m:
        head, tail = m.split("/", 1)
        from .providers import _REGISTRY  # local import to avoid cycle at import time
        if head in _REGISTRY:
            return head, tail
    return None, m


def _base_url(provider_id: str) -> str | None:
    prov = get_provider(provider_id)
    # Let LLM_BASE_URL override the base URL of the DEFAULT provider (custom endpoint).
    if provider_id == default_provider_id() and os.getenv(CUSTOM_BASE_URL_ENV):
        return os.getenv(CUSTOM_BASE_URL_ENV)
    return prov.base_url


def get_client(provider_id: str | None = None):
    """Return a cached OpenAI-compatible client for a provider (default if None)."""
    pid = (provider_id or default_provider_id()).strip()
    with _lock:
        if pid in _clients:
            return _clients[pid]
        prov = get_provider(pid)
        api_key = keys.get_api_key(pid)
        if prov.requires_key and not api_key:
            raise LLMConfigError(
                f"No API key configured for provider '{prov.label}'. Set one via the "
                f"settings/keys API or the {prov.key_env or 'LLM_API_KEY'} env var.")
        if pid == "anthropic":
            # Native Messages API behind the same chat.completions call shape —
            # prompt caching + real extended thinking (see llm.anthropic_native).
            from .anthropic_native import AnthropicNativeClient
            client: object = AnthropicNativeClient(api_key=api_key or "",
                                                   base_url=_base_url(pid))
        else:
            from openai import OpenAI
            client = OpenAI(base_url=_base_url(pid), api_key=api_key or "not-needed")
        _clients[pid] = client
        return client


def get_client_for_model(model: str | None):
    """Resolve (client, bare_model) from a possibly ``provider/model`` string."""
    pid, bare = split_model(model)
    return get_client(pid), bare


def list_provider_models(provider_id: str | None = None) -> list[str]:
    """The model ids the provider's endpoint currently serves, via the OpenAI-compatible
    ``GET /models`` (implemented by OpenAI, Groq, Mistral, NVIDIA NIM, and the local
    runtimes). Powers the UI's "Load models" — so a provider with a large or rotating
    catalog (e.g. NVIDIA) can be populated from its real, live list instead of a guessed
    hardcoded set. Raises on an unreachable/unauthorized endpoint or one without a models
    endpoint; callers handle the failure."""
    listed = get_client(provider_id).models.list()
    return [i for i in (getattr(m, "id", None) for m in (getattr(listed, "data", None) or [])) if i]


def probe_provider(provider_id: str | None = None) -> tuple[bool, str]:
    """Best-effort BYOK connectivity check. Returns (ok, detail); never raises.

    Verifies the provider is REACHABLE and the key (if any) is valid — WITHOUT requiring
    a specific model to be installed. It lists models via the standard OpenAI-compatible
    ``GET /models`` endpoint, which every backend implements (OpenAI, Groq, Mistral, and
    the local runtimes Ollama / vLLM / LM Studio / llama.cpp). This is the fix for the old
    behaviour: a 1-token completion against the shipped default model (e.g. ``llama3.1``)
    404'd whenever a local server had only OTHER models pulled — reporting a working
    provider as broken. The completion is now only a FALLBACK for gateways without a models
    endpoint (notably the native Anthropic client, whose default model always exists)."""
    prov = get_provider(provider_id)
    try:
        client = get_client(provider_id)  # may raise for a missing required key
    except Exception as e:  # noqa: BLE001
        return False, str(e)[:200]

    # Preferred check: list models — reachability + auth, independent of any installed model.
    list_err = ""
    try:
        ids = list_provider_models(provider_id)
        n = len(ids)
        if n:
            return True, f"Connected — {prov.label} reachable, {n} model{'' if n == 1 else 's'} available."
        return True, f"Connected — {prov.label} reachable (no models installed yet)."
    except Exception as e:  # noqa: BLE001 — no models endpoint, or a real connection/auth failure
        list_err = str(e)

    # Fallback: a minimal completion against the default model (works for cloud providers
    # whose default always exists, and the native Anthropic client).
    model = prov.default_model or (prov.models[0] if prov.models else "")
    if not model:
        return False, (list_err or f"{prov.label} is not reachable.")[:200]
    try:
        client.chat.completions.create(
            model=model, max_tokens=1,
            messages=[{"role": "user", "content": "ping"}])
        return True, f"Connected — {prov.label} ({model}) responded."
    except Exception as e:  # noqa: BLE001 - report any failure as a clean status
        return False, str(e)[:200]


def resolve_turn_client(model: str | None, provider: str | None = None):
    """Resolve (client, bare_model, fallback_model) for one agent turn.

    Precedence for the provider: an explicit ``provider`` argument, else a
    ``provider/model`` prefix on ``model``, else the configured default provider.
    The fallback model is the resolved provider's own default model (so a failed
    turn retries within the SAME provider/client, never on an unrelated one).

    When the provider is EXPLICIT the model is used VERBATIM — it is not split. NVIDIA NIM
    (and OpenRouter/Together) use vendor-prefixed ids like ``qwen/…``, ``nvidia/…``,
    ``openai/gpt-oss-…`` whose prefix collides with a provider id; splitting would strip a
    prefix the endpoint actually needs and send the wrong model. The prefix split only
    applies when the provider must be INFERRED from the model string.
    """
    if provider:
        pid, bare = provider, (model or "").strip()
    else:
        pid, bare = split_model(model)
    client = get_client(pid)
    prov = get_provider(pid)
    fallback = prov.default_model if (prov.default_model and prov.default_model != bare) else None
    return client, bare, fallback


def get_llm_client():
    """Back-compat accessor: the default provider's client.

    Existing call sites (agent loop, title generation, research sub-queries) keep
    working unchanged; they use the model string they already pass.
    """
    return get_client()


def reasoning_of(delta) -> str | None:
    """Extract a reasoning/thinking delta across provider shapes.

    Covers ``reasoning_content`` (Zhipu/DeepSeek/Qwen) and ``reasoning`` (some
    OpenAI-compatible gateways), via direct attribute or the SDK's model_extra.
    """
    for attr in ("reasoning_content", "reasoning"):
        val = getattr(delta, attr, None)
        if val:
            return val
    extra = getattr(delta, "model_extra", None) or {}
    return extra.get("reasoning_content") or extra.get("reasoning")


def reset_clients() -> None:
    """Drop cached clients (tests / after a key or provider change)."""
    with _lock:
        _clients.clear()
