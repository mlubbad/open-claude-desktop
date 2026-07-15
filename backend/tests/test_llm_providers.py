"""Phase 1: provider registry, BYOK key storage, and client configuration.

Replaces the old zhipuai-pinned test_llm_client with provider-shape contract
tests over the model-agnostic layer.
"""
import pytest
from ocd_core import llm, secrets
from ocd_core.llm import client as llm_client
from ocd_core.llm import keys as llm_keys


@pytest.fixture(autouse=True)
def _mem_store(monkeypatch):
    # Deterministic, no OS keychain: use the in-memory secret store.
    monkeypatch.setenv("OCD_SECRET_BACKEND", "memory")
    secrets.reset_store()
    llm_client.reset_clients()
    yield
    secrets.reset_store()
    llm_client.reset_clients()


def test_registry_has_core_providers():
    ids = {p.id for p in llm.list_providers()}
    for expected in ("openai", "zhipu", "deepseek", "ollama", "openrouter", "vllm"):
        assert expected in ids


def test_hosted_providers_offer_a_model_list_including_their_default():
    for p in llm.list_providers():
        if p.is_local:
            continue  # local runtimes list whatever the user has pulled
        assert p.models, f"{p.id} should offer a model list"
        assert p.default_model in p.models, f"{p.id} default not in its models"


def test_expanded_catalog_covers_popular_open_models():
    by_id = {p.id for p in llm.list_providers()}
    assert {"openrouter", "together", "groq", "mistral"} <= by_id
    groq = next(p for p in llm.list_providers() if p.id == "groq")
    assert len(groq.models) >= 3


def test_default_provider_env_override(monkeypatch):
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    assert llm.default_provider_id() == "zhipu"  # parity default
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    assert llm.default_provider_id() == "openai"


def test_unknown_provider_resolves_to_custom(monkeypatch):
    monkeypatch.setenv("LLM_BASE_URL", "http://my-endpoint/v1")
    prov = llm.get_provider("my-custom-thing")
    assert prov.id == "my-custom-thing"
    assert prov.base_url == "http://my-endpoint/v1"
    assert prov.requires_key is False


def test_byok_roundtrip_and_env_fallback(monkeypatch):
    # Nothing stored, no env -> no key, provider not usable.
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    assert llm_keys.get_api_key("deepseek") is None
    assert llm_keys.has_key("deepseek") is False
    # Stored key wins.
    llm_keys.set_api_key("deepseek", "sk-stored")
    assert llm_keys.get_api_key("deepseek") == "sk-stored"
    assert llm_keys.has_key("deepseek") is True
    llm_keys.delete_api_key("deepseek")
    # Falls back to the provider env var when nothing stored.
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-env")
    assert llm_keys.get_api_key("deepseek") == "sk-env"


def test_local_provider_needs_no_key(monkeypatch):
    monkeypatch.delenv("OLLAMA_API_KEY", raising=False)
    assert llm_keys.has_key("ollama") is True  # local runtimes are always usable


def test_has_key_map_matches_serial_reads(monkeypatch):
    # The concurrent sweep the /providers route uses must agree with per-provider has_key.
    for env in ("OPENAI_API_KEY", "DEEPSEEK_API_KEY", "GROQ_API_KEY", "MISTRAL_API_KEY"):
        monkeypatch.delenv(env, raising=False)
    llm_keys.set_api_key("deepseek", "sk-stored")
    ids = ["openai", "deepseek", "ollama", "vllm", "groq"]
    result = llm_keys.has_key_map(ids)
    assert result == {pid: llm_keys.has_key(pid) for pid in ids}
    # Spot-check the semantics: local providers usable, only the keyed one is set.
    assert result["deepseek"] is True
    assert result["openai"] is False and result["groq"] is False
    assert result["ollama"] is True and result["vllm"] is True  # local


def test_has_key_map_handles_empty_and_single():
    assert llm_keys.has_key_map([]) == {}
    assert llm_keys.has_key_map(["ollama"]) == {"ollama": True}


def test_get_client_requires_key_for_hosted(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    with pytest.raises(llm.LLMConfigError):
        llm.get_client("openai")


def test_get_client_uses_provider_base_url():
    llm_keys.set_api_key("deepseek", "sk-x")
    client = llm.get_client("deepseek")
    assert "api.deepseek.com" in str(client.base_url)


def test_get_client_local_base_url_no_key():
    client = llm.get_client("ollama")  # no key needed
    assert "localhost:11434" in str(client.base_url)


def test_split_model_provider_prefix():
    assert llm.split_model("openai/gpt-4o") == ("openai", "gpt-4o")
    assert llm.split_model("glm-4-plus") == (None, "glm-4-plus")
    # A vendor/model name for a NON-provider prefix stays intact (OpenRouter style).
    assert llm.split_model("meta-llama/Llama-3.3-70B") == (None, "meta-llama/Llama-3.3-70B")


def test_reasoning_of_normalizes_shapes():
    class D:
        reasoning_content = "thinking hard"
    assert llm.reasoning_of(D()) == "thinking hard"

    class D2:
        reasoning = "alt field"
    assert llm.reasoning_of(D2()) == "alt field"

    class D3:
        content = "answer"
    assert llm.reasoning_of(D3()) is None


def test_resolve_turn_client_explicit_provider():
    client, model, fallback = llm.resolve_turn_client("llama3.1", provider="ollama")
    assert "localhost:11434" in str(client.base_url)
    assert model == "llama3.1"
    # ollama's default_model is llama3.1 (== requested) -> no self-fallback
    assert fallback is None


def _fake_client(create):
    import types
    return types.SimpleNamespace(
        chat=types.SimpleNamespace(completions=types.SimpleNamespace(create=create)))


def _client_with_models(model_ids, create=None):
    """A fake client exposing the OpenAI-compatible ``models.list()`` (and optionally a
    completion `create` — which the probe must NOT reach when models.list() succeeds)."""
    import types
    def _list():
        return types.SimpleNamespace(data=[types.SimpleNamespace(id=i) for i in model_ids])
    def _boom(**_kw):
        raise AssertionError("completion must not run when /models works")
    return types.SimpleNamespace(
        models=types.SimpleNamespace(list=_list),
        chat=types.SimpleNamespace(completions=types.SimpleNamespace(create=create or _boom)))


def test_probe_lists_models_without_needing_the_default_installed(monkeypatch):
    """The fix: a local runtime with only OTHER models pulled tests as CONNECTED — the
    probe lists models instead of completing against the (possibly-missing) default."""
    monkeypatch.setattr(llm_client, "get_client",
                        lambda pid=None: _client_with_models(["fast-llama", "qwen2.5"]))
    ok, detail = llm.probe_provider("ollama")  # ships default "llama3.1", NOT installed here
    assert ok is True
    assert "2 models" in detail and "reachable" in detail


def test_probe_reports_reachable_when_no_models_installed(monkeypatch):
    monkeypatch.setattr(llm_client, "get_client", lambda pid=None: _client_with_models([]))
    ok, detail = llm.probe_provider("ollama")
    assert ok is True and "no models installed" in detail.lower()


def test_probe_without_models_endpoint_falls_back_to_a_completion(monkeypatch):
    # A gateway without /models (fake client has no `.models`) → the 1-token completion
    # fallback still verifies connectivity (this is the Anthropic-native path).
    def create(model, **kw):
        assert kw.get("max_tokens") == 1  # minimal, cheap probe
        return "ok"
    monkeypatch.setattr(llm_client, "get_client", lambda pid=None: _fake_client(create))
    ok, detail = llm.probe_provider("deepseek")
    assert ok is True and "Connected" in detail


def test_probe_reports_error(monkeypatch):
    # models.list() raises (unreachable/auth); the completion fallback surfaces the failure.
    def create(model, **kw):
        raise RuntimeError("401 unauthorized")
    monkeypatch.setattr(llm_client, "get_client", lambda pid=None: _fake_client(create))
    ok, detail = llm.probe_provider("deepseek")
    assert ok is False and "401" in detail


def test_probe_without_installed_default_surfaces_connection_error(monkeypatch):
    # vllm has no default model; if /models is unreachable there's nothing to complete
    # with, so the connection error is reported (not a misleading "no model" message).
    import types
    def boom_list():
        raise RuntimeError("connection refused")
    fake = types.SimpleNamespace(
        models=types.SimpleNamespace(list=boom_list),
        chat=types.SimpleNamespace(completions=types.SimpleNamespace(
            create=lambda **_k: (_ for _ in ()).throw(AssertionError("no model to complete with")))))
    monkeypatch.setattr(llm_client, "get_client", lambda pid=None: fake)
    ok, detail = llm.probe_provider("vllm")
    assert ok is False and "connection refused" in detail


def test_resolve_turn_client_prefix_and_fallback(monkeypatch):
    llm_keys.set_api_key("deepseek", "sk-x")
    client, model, fallback = llm.resolve_turn_client("deepseek/deepseek-reasoner")
    assert "api.deepseek.com" in str(client.base_url)
    assert model == "deepseek-reasoner"
    # provider default (deepseek-chat) differs from requested -> it's the fallback
    assert fallback == "deepseek-chat"


def test_resolve_turn_client_missing_key_raises(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    with pytest.raises(llm.LLMConfigError):
        llm.resolve_turn_client("gpt-4o", provider="openai")


# ---- NVIDIA NIM provider + live model loading ------------------------------------------

def test_nvidia_provider_in_catalog():
    assert "nvidia" in {p.id for p in llm.list_providers()}
    p = llm.get_provider("nvidia")
    assert "integrate.api.nvidia.com" in (p.base_url or "")
    assert p.requires_key is True and p.is_local is False
    assert p.default_model == "z-ai/glm-5.2" and "z-ai/glm-5.2" in p.models


def test_explicit_provider_keeps_vendor_prefixed_model_verbatim():
    # NVIDIA/OpenRouter-style ids whose vendor prefix collides with a provider id
    # ("qwen/", "nvidia/", "openai/") must NOT be split when the provider is explicit —
    # the endpoint needs the FULL id, else the wrong model is sent.
    llm_keys.set_api_key("nvidia", "sk-x")
    for mid in ("qwen/qwen2.5-coder-32b-instruct",
                "nvidia/llama-3.1-nemotron-70b-instruct",
                "openai/gpt-oss-120b", "z-ai/glm-5.2"):
        _client, model, _fallback = llm.resolve_turn_client(mid, provider="nvidia")
        assert model == mid  # verbatim, prefix intact


def test_list_provider_models_returns_live_ids(monkeypatch):
    monkeypatch.setattr(llm_client, "get_client",
                        lambda pid=None: _client_with_models(["a", "b", "c"]))
    assert llm.list_provider_models("nvidia") == ["a", "b", "c"]


def test_available_models_route_lists_and_reports_failure(monkeypatch):
    from app.main import app
    from fastapi.testclient import TestClient
    c = TestClient(app)
    monkeypatch.setattr(llm_client, "get_client",
                        lambda pid=None: _client_with_models(["z-ai/glm-5.2", "meta/llama-3.3-70b-instruct"]))
    ok = c.get("/providers/nvidia/available-models").json()
    assert ok["ok"] is True and "z-ai/glm-5.2" in ok["models"]

    def boom(pid=None):
        raise RuntimeError("connection refused")
    monkeypatch.setattr(llm_client, "get_client", boom)
    bad = c.get("/providers/nvidia/available-models").json()
    assert bad["ok"] is False and bad["models"] == [] and "connection refused" in bad["detail"]
