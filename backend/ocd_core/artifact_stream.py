"""Incremental extraction of an artifact tool call's fields from *streaming* JSON
tool-call arguments, so the artifact's content can be shown live as the model writes it
(true token-streaming) instead of appearing all at once when the tool completes.

Pure + dependency-free: feed the accumulated ``arguments`` string (the full text so far)
and get back an optional open-signal (once we can name the artifact) plus the newly
available slice of decoded ``content``. Handles JSON string escapes and holds back
partial escape sequences at the buffer edge, and tolerates keys arriving in any order.
"""
from __future__ import annotations

import re

CREATE = "create_artifact"
UPDATE = "update_artifact"


def _value_start(buf: str, key: str) -> int:
    """Index just after the opening quote of ``key``'s string value, or -1 if the key +
    opening quote haven't arrived yet."""
    m = re.search(r'"' + re.escape(key) + r'"\s*:\s*"', buf)
    return m.end() if m else -1


_ESCAPES = {'"': '"', "\\": "\\", "/": "/", "b": "\b", "f": "\f",
            "n": "\n", "r": "\r", "t": "\t"}


def _decode_partial(buf: str, start: int) -> tuple[str, bool]:
    """Decode the JSON string beginning at ``start`` (just past the opening quote).

    Returns ``(decoded, complete)``. Stops at the first unescaped ``"`` (complete=True)
    or the end of the buffer (complete=False). A trailing lone backslash or a truncated
    ``\\uXXXX`` at the edge is held back so it isn't mis-decoded mid-escape.
    """
    out: list[str] = []
    i, n = start, len(buf)
    while i < n:
        c = buf[i]
        if c == "\\":
            if i + 1 >= n:
                break  # incomplete escape at the edge — hold back
            e = buf[i + 1]
            if e in _ESCAPES:
                out.append(_ESCAPES[e])
                i += 2
                continue
            if e == "u":
                if i + 6 > n:
                    break  # truncated \uXXXX — hold back
                try:
                    out.append(chr(int(buf[i + 2:i + 6], 16)))
                except ValueError:
                    out.append(buf[i:i + 6])
                i += 6
                continue
            out.append(e)  # unknown escape — keep the escaped char literally
            i += 2
            continue
        if c == '"':
            return "".join(out), True
        out.append(c)
        i += 1
    return "".join(out), False


def _complete_str(buf: str, key: str) -> str | None:
    """The fully-decoded value of ``key`` if its closing quote has arrived, else None."""
    s = _value_start(buf, key)
    if s == -1:
        return None
    decoded, done = _decode_partial(buf, s)
    return decoded if done else None


class ArtifactArgStream:
    """Stateful, per-tool-call incremental reader for an artifact tool's arguments.

    Construct with the tool name and the tool-call id, then ``feed(accumulated_args)``
    repeatedly. Emits the open signal exactly once (when we can identify the artifact and
    its content has begun) and, thereafter, only the newly-arrived tail of the content.
    """

    def __init__(self, tool_name: str, call_id: str) -> None:
        self.is_update = tool_name == UPDATE
        self.call_id = call_id
        self._opened = False
        self._emitted = ""
        self.artifact_id = ""

    def feed(self, buf: str) -> tuple[dict | None, str]:
        """Returns ``(open_meta | None, content_delta)`` for the current buffer."""
        open_meta = None
        if not self._opened and _value_start(buf, "content") != -1:
            # For an update the target id lives in the args and must be complete before we
            # can address the right artifact; for a create we key by the tool-call id.
            aid = _complete_str(buf, "id") if self.is_update else self.call_id
            if aid:
                self.artifact_id = aid
                self._opened = True
                open_meta = {
                    "id": aid,
                    "title": _complete_str(buf, "title") or "Untitled",
                    # kind/language are absent on updates — left blank, the client keeps
                    # the existing values.
                    "kind": "" if self.is_update else (_complete_str(buf, "kind") or "markdown"),
                    "language": _complete_str(buf, "language") or "",
                }

        delta = ""
        if self._opened:
            s = _value_start(buf, "content")
            if s != -1:
                decoded, _done = _decode_partial(buf, s)
                if len(decoded) > len(self._emitted):
                    delta = decoded[len(self._emitted):]
                    self._emitted = decoded
        return open_meta, delta
