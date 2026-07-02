"""Phase 1: offline model-capability lookup."""
from ocd_core.llm import catalog


def test_known_models_capabilities():
    gpt4o = catalog.capabilities("gpt-4o")
    assert gpt4o.vision is True and gpt4o.tools is True and gpt4o.context_window >= 128_000

    reasoner = catalog.capabilities("deepseek-reasoner")
    assert reasoner.reasoning is True

    glm = catalog.capabilities("glm-4-plus")
    assert glm.tools is True


def test_provider_prefix_is_stripped():
    assert catalog.supports_vision("openai/gpt-4o") is True


def test_unknown_model_gets_safe_defaults():
    caps = catalog.capabilities("some-unknown-model-xyz")
    assert caps.tools is True
    assert caps.context_window >= 4096
    assert caps.vision is False


def test_helpers():
    assert catalog.context_window("glm-4-long") >= 1_000_000
    assert catalog.supports_reasoning("glm-4.5-air") is True
