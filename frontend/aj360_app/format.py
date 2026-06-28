"""Pure presentation formatters (no I/O, no ocd_core).

Copied verbatim from the backend so the thin frontend stays dependency-free:
- ``fmt_bytes`` from ``backend/ocd_core/util.py``
- ``strip_answer_label`` from ``backend/ocd_core/agent.py`` (originally the
  private ``_strip_answer_label``; renamed public here, body unchanged).

Behavior parity with the backend is the contract — do NOT "improve" the logic
here; change the call sites instead if behavior must evolve.
"""
from __future__ import annotations

import re


def fmt_bytes(n) -> str:
    if not n:
        return "0 B"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.1f} {unit}"
        n /= 1024


_LABEL_RE = re.compile(
    r"^\s*(?:#{1,6}\s*)?(?:\*\*)?\s*"
    r"(?:corrected|final|verified|revised|improved)\s+answer\s*(?:\*\*)?\s*:?\s*\n+",
    re.IGNORECASE)


def strip_answer_label(text: str) -> str:
    """Drop a leading 'Corrected Answer'/'Final Answer' heading the verify pass may
    still emit, so the refined answer reads as a seamless replacement."""
    return _LABEL_RE.sub("", text, count=1).lstrip()
