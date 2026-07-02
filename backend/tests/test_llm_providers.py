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
