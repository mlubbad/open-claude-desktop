"""Vision fallback: make attached images usable by ANY model (root-cause fix for the
'I can't see the image' bug on text-only models)."""
import types

import pytest
from ocd_core import secrets, vision
from ocd_core.llm import client as llm_client
from ocd_core.llm import keys as llm_keys

URI = "data:image/png;base64,iVBORw0KGgo="


@pytest.fixture(autouse=True)
def _mem_store(monkeypatch):
    monkeypatch.setenv("OCD_SECRET_BACKEND", "memory")
    secrets.reset_store()
    llm_client.reset_clients()
    yield
    secrets.reset_store()
    llm_client.reset_clients()


def _streaming_client(text: str):
    """A fake OpenAI-compatible client whose completion streams `text` as delta chunks."""
    def _create(model, messages, max_tokens=None, stream=False, **_kw):
        for ch in (text[i:i + 5] for i in range(0, len(text), 5)):
            yield types.SimpleNamespace(
                choices=[types.SimpleNamespace(delta=types.SimpleNamespace(content=ch))])
    return types.SimpleNamespace(
        chat=types.SimpleNamespace(completions=types.SimpleNamespace(create=_create)))


def test_no_vision_provider_yields_a_clear_notice(monkeypatch):
    # No provider keys → no vision provider available → a notice, never a fake description.
    monkeypatch.setattr(vision, "_pick", lambda: None)
    assert vision.available() is False
    note = vision.image_context([URI])
    assert "cannot view images" in note
    assert "Do NOT pretend" in note


def test_describe_images_uses_the_first_keyed_vision_provider(monkeypatch):
    # A vision provider with a key is used to describe the image; its text comes back.
    llm_keys.set_api_key("openai", "sk-x")
    seen = {}

    def _resolve(model, provider=None):
        seen["provider"], seen["model"] = provider, model
        return _streaming_client("A bar chart of monthly revenue."), model, None

    monkeypatch.setattr("ocd_core.llm.resolve_turn_client", _resolve)
    desc = vision.describe_images([URI])
    assert desc == "A bar chart of monthly revenue."
    assert seen["provider"] == "openai"  # first keyed candidate


def test_image_context_wraps_the_description(monkeypatch):
    monkeypatch.setattr(vision, "describe_images", lambda imgs, **_k: "a table of KPIs")
    note = vision.image_context([URI, URI])
    assert "a table of KPIs" in note
    assert "vision model" in note  # framed as the image content, not a guess


def test_describe_images_none_when_empty(monkeypatch):
    monkeypatch.setattr(vision, "_pick", lambda: ("openai", "gpt-4o"))
    assert vision.describe_images([]) is None
