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


# --- markdown sanitization for untrusted (model / DB / web) content ---------- #
# react-markdown here runs with rehype-raw (raw HTML passthrough) and auto-loads
# remote images, so unsanitized content is a prompt-injection exfiltration / XSS
# vector. Neutralize the loading/executing bits; leave ordinary markdown intact.
_MD_IMG_REMOTE = re.compile(r"!\[([^\]]*)\]\(\s*(?:https?:)?//[^)]*\)")
_RAW_SCRIPT = re.compile(r"(?is)<\s*script\b.*?<\s*/\s*script\s*>")
_EVENT_HANDLER = re.compile(r"""(?is)\son\w+\s*=\s*("[^"]*"|'[^']*'|[^\s>]+)""")
_DANGER_TAG = re.compile(
    r"(?is)<\s*/?\s*(?:script|img|iframe|embed|object|link|svg|video|audio|source"
    r"|base|meta|form|input|style|applet|frame|frameset)\b[^>]*>")
_DANGER_SCHEME = re.compile(r"(?i)\b(?:javascript|vbscript)\s*:|data\s*:\s*text/html")


def sanitize_markdown(text: str) -> str:
    """Neutralize exfiltration/XSS vectors in untrusted markdown before it renders:
    remote images (privacy beacons), raw HTML that loads or executes (script/img/
    iframe/...), inline event handlers, and dangerous URL schemes. Ordinary markdown
    text, formatting and safe/relative links are left intact. Idempotent, so it is
    safe to re-run on the accumulating buffer as a stream arrives."""
    if not text:
        return text
    s = _MD_IMG_REMOTE.sub(r"[\1]", text)   # remote images -> alt text only (no beacon)
    s = _RAW_SCRIPT.sub("", s)               # <script>...</script>
    s = _EVENT_HANDLER.sub("", s)            # onerror=/onload=/...
    s = _DANGER_TAG.sub("", s)               # remote-loading / executing HTML tags
    s = _DANGER_SCHEME.sub("blocked:", s)    # javascript:/vbscript:/data:text/html
    return s
