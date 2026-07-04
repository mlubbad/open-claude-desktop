"""User profile rendering + injection into the turn's system prompt."""
import asyncio

import pytest
from ocd_core import agent, profile, secrets
from ocd_core.llm import client as llm_client


def test_render_and_sanitize():
    assert profile.render({}) == ""
    text = profile.render({"call_me": "Sam", "role": "data analyst",
                           "preferences": "be concise"})
    assert "Sam" in text and "data analyst" in text and "be concise" in text
    # sanitize drops unknown keys + empties, trims strings
    clean = profile.sanitize({"call_me": "  Sam  ", "bogus": "x", "role": ""})
    assert clean == {"call_me": "Sam"}


@pytest.fixture
def _env(monkeypatch):
    monkeypatch.setenv("OCD_SECRET_BACKEND", "memory")
    secrets.reset_store()
    llm_client.reset_clients()
    monkeypatch.setattr(agent, "resolve_turn_client",
                        lambda model, provider=None: (object(), model, None))
    monkeypatch.setattr(agent.schema_catalog, "ensure_catalog", lambda: None)
    yield
    secrets.reset_store()
    llm_client.reset_clients()


def test_profile_reaches_the_system_prompt(monkeypatch, _env):
    seen = {}

    async def _fake_stream(llm, model, messages, tools, temperature, max_tokens,
                           content_scope="answer", fallback_model=None):
        seen["system"] = messages[0]["content"]
        yield {"__done__": {"content": "hi", "tool_calls": [], "note": None}}

    monkeypatch.setattr(agent, "_stream_llm", _fake_stream)

    async def scenario():
        async for _ in agent.run_turn("hi", [], None, "m", effort="Low",
                                      user_profile="Address the user as Sam."):
            pass

    asyncio.run(scenario())
    assert "USER PROFILE" in seen["system"]
    assert "Address the user as Sam." in seen["system"]
