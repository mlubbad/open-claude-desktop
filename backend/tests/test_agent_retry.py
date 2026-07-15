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


class RateLimitWithHeader(Exception):
    """A 429 carrying a Retry-After header, like the OpenAI/Anthropic SDK exceptions."""

    def __init__(self, retry_after="2"):
        super().__init__("Error code: 429 - Too Many Requests")
        self.status_code = 429
        self.response = types.SimpleNamespace(headers={"retry-after": retry_after})


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


# --- Retry-After / backoff helpers ------------------------------------------- #

def test_retry_after_seconds_parses_header():
    assert agent._retry_after_seconds(RateLimitWithHeader("7")) == 7.0
    assert agent._retry_after_seconds(RateLimit()) is None        # no response/header
    assert agent._retry_after_seconds(ValueError("nope")) is None


def test_backoff_delay_honors_retry_after_capped():
    assert agent._backoff_delay(0, 5.0) == 5.0                    # honored verbatim
    assert agent._backoff_delay(0, 9_999.0) == agent._RETRY_AFTER_CAP  # capped
    d = agent._backoff_delay(3, None)                             # exponential + jitter
    assert 0 < d <= agent._BACKOFF_CAP


def test_friendly_error_explains_rate_limit():
    msg = agent._friendly_error("Error code: 429 - {'title': 'Too Many Requests'}")
    assert "rate-limit" in msg.lower()
    assert agent._friendly_error("boom") == "LLM call failed: boom"


# --- Streaming path: the actual 429 regression ------------------------------- #

def _streaming_llm(create):
    return types.SimpleNamespace(
        chat=types.SimpleNamespace(completions=types.SimpleNamespace(create=create)))


@pytest.fixture
def no_thread_sleep(monkeypatch):
    monkeypatch.setattr(agent.time, "sleep", lambda *_a, **_k: None)


def test_stream_chunks_retries_rate_limit_before_first_chunk(no_thread_sleep):
    """A 429 raised BEFORE any chunk is backed off and retried, not fatal."""
    calls = {"n": 0}

    def create(model, **kw):
        calls["n"] += 1
        if calls["n"] < 3:
            raise RateLimitWithHeader("0")
        return iter(["a", "b"])

    async def collect():
        out = []
        async for c in agent._stream_chunks(_streaming_llm(create), "m", [], None,
                                            0.1, 100, extra={}):
            out.append(c)
        return out

    assert asyncio.run(collect()) == ["a", "b"]
    assert calls["n"] == 3  # two 429s retried, then the stream succeeds


def test_stream_chunks_gives_up_after_budget(no_thread_sleep):
    """A persistent 429 eventually re-raises (so the caller can fall back / report)."""
    def create(model, **kw):
        raise RateLimitWithHeader("0")

    async def collect():
        async for _ in agent._stream_chunks(_streaming_llm(create), "m", [], None,
                                            0.1, 100, extra={}):
            pass

    with pytest.raises(Exception) as ei:
        asyncio.run(collect())
    assert getattr(ei.value, "status_code", None) == 429
