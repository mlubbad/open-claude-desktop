"""Transient-error retry/backoff for LLM calls: the _is_retryable classifier and the
_create_with_retry loop (retryable-then-success, non-retryable-raises, exhaustion)."""
import asyncio
import types

import pytest
from ocd_core import agent


class RateLimit(Exception):
    def __init__(self):
        super().__init__("429")
        self.status_code = 429


class BadRequest(Exception):
    def __init__(self):
        super().__init__("400")
        self.status_code = 400


class APITimeoutError(Exception):  # name-based hint, no status
    pass


def test_is_retryable_by_status():
    assert agent._is_retryable(RateLimit()) is True
    assert agent._is_retryable(BadRequest()) is False


def test_is_retryable_by_name():
    assert agent._is_retryable(APITimeoutError()) is True
    assert agent._is_retryable(ValueError("nope")) is False


def _fake_llm(create):
    return types.SimpleNamespace(chat=types.SimpleNamespace(completions=types.SimpleNamespace(create=create)))


@pytest.fixture
def no_sleep(monkeypatch):
    async def _instant(_):
        return None
    monkeypatch.setattr(agent.asyncio, "sleep", _instant)


def test_retries_transient_then_succeeds(no_sleep):
    calls = {"n": 0}

    def create(model, **kw):
        calls["n"] += 1
        if calls["n"] < 3:
            raise RateLimit()
        return "ok"

    out = asyncio.run(agent._create_with_retry(_fake_llm(create), "m", {}, retries=2))
    assert out == "ok"
    assert calls["n"] == 3  # 1 initial + 2 retries


def test_non_retryable_raises_immediately(no_sleep):
    calls = {"n": 0}

    def create(model, **kw):
        calls["n"] += 1
        raise BadRequest()

    with pytest.raises(BadRequest):
        asyncio.run(agent._create_with_retry(_fake_llm(create), "m", {}, retries=2))
    assert calls["n"] == 1  # no retries for a permanent error


def test_exhausts_retries_then_raises(no_sleep):
    calls = {"n": 0}

    def create(model, **kw):
        calls["n"] += 1
        raise RateLimit()

    with pytest.raises(RateLimit):
        asyncio.run(agent._create_with_retry(_fake_llm(create), "m", {}, retries=2))
    assert calls["n"] == 3  # 1 + 2 retries, then gives up


def test_llm_create_falls_back_after_retries(no_sleep):
    seen = []

    def create(model, **kw):
        seen.append(model)
        if model == "primary":
            raise RateLimit()
        return "fallback-response"

    resp, note = asyncio.run(
        agent._llm_create(_fake_llm(create), "primary", [], fallback_model="default"))
    assert resp == "fallback-response"
    assert "fell back to default" in note
    # primary tried 3x (1+2 retries) before falling back to default.
    assert seen.count("primary") == 3
    assert "default" in seen
