"""Opt-in Opik observability — a non-intrusive event tap over the agent loop.

Rather than decorating functions inside ``agent.run_turn`` (which would couple the
core loop to an observability vendor), the tracer wraps the turn's EVENT STREAM:
``traced(...)`` is an async pass-through generator the routes lay over ``run_turn``.
Every event flows to the client unchanged; on the side, the tap assembles an Opik
trace — one trace per turn, a ``tool`` span per tool call (closed by its id-matched
result/error), a ``general`` span per thinking phase, the final answer as the trace
output, and the turn's usage event as metadata.

Design rules:
  * OFF by default; enabled via settings (``opik_enabled`` + ``opik_url`` +
    ``opik_project``) or env (OPIK_URL_OVERRIDE / OPIK_PROJECT_NAME). The ``opik``
    package is an optional extra — absent, everything silently no-ops.
  * Observability must never break or slow a turn: every SDK call is guarded, and
    the first failure disables tracing for the rest of the process (logged once).
  * No secrets in settings.json: an Opik Cloud API key comes only from the
    OPIK_API_KEY environment variable; self-hosted needs none.
"""
from __future__ import annotations

import logging
import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime

from . import settings

log = logging.getLogger(__name__)

# Process-wide client cache + one-way failure latch (observability must not retry
# itself into the request path).
_state: dict = {"client": None, "cfg": None, "failed": False}


def config() -> dict | None:
    """The active Opik config, or None when tracing is off/unavailable."""
    if _state["failed"]:
        return None
    s = settings.get_settings()
    enabled = bool(s.get("opik_enabled")) or os.getenv("OPIK_ENABLED", "").lower() in ("1", "true")
    if not enabled:
        return None
    return {
        "host": (s.get("opik_url") or os.getenv("OPIK_URL_OVERRIDE") or "").strip() or None,
        "project": (s.get("opik_project") or os.getenv("OPIK_PROJECT_NAME") or "").strip()
                   or "open-claude-desktop",
    }


def _client(cfg: dict):
    """Lazily import + build the Opik client; None if the SDK is missing/broken."""
    if _state["client"] is not None and _state["cfg"] == cfg:
        return _state["client"]
    try:
        import opik  # optional extra: pip install ocd-backend[observability]
        _state["client"] = opik.Opik(
            project_name=cfg["project"], host=cfg["host"],
            api_key=os.getenv("OPIK_API_KEY") or None)
        _state["cfg"] = cfg
        return _state["client"]
    except Exception as e:  # noqa: BLE001 - missing package, bad config…
        _disable(f"Opik client unavailable: {e}")
        return None


def _disable(reason: str) -> None:
    if not _state["failed"]:
        log.warning("%s — tracing disabled for this session.", reason)
    _state["failed"] = True
    _state["client"] = None


def flush(timeout: int = 5) -> bool:
    """Best-effort flush of the background batch queue (eval scripts, shutdown)."""
    c = _state["client"]
    if c is None:
        return True
    try:
        return bool(c.flush(timeout=timeout))
    except Exception:  # noqa: BLE001
        return False


async def traced(events: AsyncIterator[dict], *, goal: str, model: str,
                 provider: str | None = None, effort: str = "",
                 turn_id: str | None = None,
                 tags: list[str] | None = None) -> AsyncIterator[dict]:
    """Pass ``events`` through unchanged while mirroring them into an Opik trace.

    The tap is deliberately forgiving: any SDK failure flips the process-wide
    disable latch and the remainder of the stream flows untouched."""
    cfg = config()
    client = _client(cfg) if cfg else None
    if client is None:
        async for ev in events:
            yield ev
        return

    trace = None
    # Spans are emitted as ONE-SHOT completed records (start_time + end_time + output
    # in a single trace.span() call) instead of span()/end() pairs — Opik's batching
    # can lose the update when end() lands right after creation, and the SDK warns
    # about exactly that pattern. Until then, in-flight work is just bookkeeping:
    pending_tools: dict[str, dict] = {}   # tool_call id -> {name, input, start}
    pending_think: dict | None = None     # {phase, start}
    answer: list[str] = []
    usage_meta: dict | None = None
    error_text: str | None = None

    def _now() -> datetime:
        return datetime.now(UTC)

    try:
        trace = client.trace(
            name="agent_turn", input={"goal": goal},
            metadata={"model": model, "provider": provider or "", "effort": effort},
            tags=["agent"] + (tags or []), thread_id=turn_id,
            project_name=cfg["project"])
    except Exception as e:  # noqa: BLE001
        _disable(f"Opik trace open failed: {e}")

    def _tap(ev: dict) -> None:
        nonlocal pending_think, usage_meta, error_text
        t = ev.get("type")
        if t == "tool":
            pending_tools[ev.get("id", "")] = {
                "name": ev.get("name", "tool"), "input": ev.get("input", ""),
                "start": _now()}
        elif t in ("tool_result", "tool_error"):
            call = pending_tools.pop(ev.get("id", ""), None)
            if call is not None:
                if t == "tool_result":
                    trace.span(name=call["name"], type="tool",
                               start_time=call["start"], end_time=_now(),
                               input={"input": call["input"]},
                               output={"summary": ev.get("summary", "")})
                else:
                    msg = ev.get("text", "tool failed")
                    trace.span(name=call["name"], type="tool",
                               start_time=call["start"], end_time=_now(),
                               input={"input": call["input"]},
                               output={"error": msg},
                               error_info={"exception_type": "ToolError",
                                           "message": msg, "traceback": ""})
        elif t == "think_open":
            pending_think = {"phase": ev.get("phase", ""), "start": _now()}
        elif t == "think_close" and pending_think is not None:
            trace.span(name=f"think:{pending_think['phase']}", type="general",
                       start_time=pending_think["start"], end_time=_now())
            pending_think = None
        elif t == "answer_open":
            answer.clear()  # a later answer block supersedes narration (loop contract)
        elif t == "delta" and ev.get("scope") == "answer":
            answer.append(ev.get("text", ""))
        elif t == "usage":
            usage_meta = {k: v for k, v in ev.items() if k != "type"}
        elif t == "error":
            error_text = ev.get("text", "error")

    try:
        async for ev in events:
            if trace is not None and not _state["failed"]:
                try:
                    _tap(ev)
                except Exception as e:  # noqa: BLE001
                    _disable(f"Opik span capture failed: {e}")
            yield ev
    finally:
        if trace is not None:
            try:
                for call in pending_tools.values():   # interrupted mid-call
                    trace.span(name=call["name"], type="tool",
                               start_time=call["start"], end_time=_now(),
                               input={"input": call["input"]},
                               output={"summary": "(interrupted)"})
                if pending_think is not None:
                    trace.span(name=f"think:{pending_think['phase']}", type="general",
                               start_time=pending_think["start"], end_time=_now())
                meta = {"usage": usage_meta} if usage_meta else None
                if error_text is not None:
                    trace.end(output={"answer": "".join(answer), "error": error_text},
                              metadata=meta,
                              error_info={"exception_type": "TurnError",
                                          "message": error_text, "traceback": ""})
                else:
                    trace.end(output={"answer": "".join(answer)}, metadata=meta)
            except Exception as e:  # noqa: BLE001
                _disable(f"Opik trace close failed: {e}")


def reset_for_tests() -> None:
    """Drop the cached client + failure latch (unit tests only)."""
    _state.update({"client": None, "cfg": None, "failed": False})
