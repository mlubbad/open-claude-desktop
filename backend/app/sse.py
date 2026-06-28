from __future__ import annotations

import json

from sse_starlette.sse import ServerSentEvent


def format_event(ev: dict) -> ServerSentEvent:
    """One run_turn event dict -> an SSE frame (event: <type>, data: <json>)."""
    return ServerSentEvent(event=ev.get("type", "message"), data=json.dumps(ev, default=str))
