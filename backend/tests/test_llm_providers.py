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


def test_probe_provider_success(monkeypatch):
    def create(model, **kw):
        assert kw.get("max_tokens") == 1  # minimal, cheap probe
        return "ok"
    monkeypatch.setattr(llm_client, "get_client", lambda pid=None: _fake_client(create))
    ok, detail = llm.probe_provider("deepseek")
    assert ok is True
    assert "Connected" in detail


def test_probe_provider_reports_error(monkeypatch):
    def create(model, **kw):
        raise RuntimeError("401 unauthorized")
    monkeypatch.setattr(llm_client, "get_client", lambda pid=None: _fake_client(create))
    ok, detail = llm.probe_provider("deepseek")
    assert ok is False
    assert "401" in detail


def test_probe_provider_without_a_model_does_not_connect(monkeypatch):
    calls = {"n": 0}
    monkeypatch.setattr(llm_client, "get_client",
                        lambda pid=None: calls.__setitem__("n", calls["n"] + 1))
    ok, detail = llm.probe_provider("vllm")  # no default_model, empty models
    assert ok is False
    assert "No model" in detail
    assert calls["n"] == 0  # never attempted a connection


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
