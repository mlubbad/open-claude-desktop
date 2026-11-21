"""Defense-in-depth against prompt-injection exfil: redact known secret SHAPES
(API keys, tokens, private keys) from AGENT-CONTROLLED outbound content before
it leaves the process -- so an injected prompt can't smuggle the user's keys
out even to an approved/trusted destination.

Deliberately "redact, don't block": a false positive just masks a substring in
a request the agent already chose to send -- it never fails the request. Only
high-signal, well-known secret shapes are matched (no generic long-hex/base64)
to keep the false-positive rate low.

Scope is content the AGENT writes into a request -- web_fetch's URL query,
web_search's query, MCP tool args -- NEVER headers: the app legitimately sends
the USER's own keys to configured endpoints via Authorization/auth headers
(connectors, MCP OAuth), and redacting those would break them. This module has
no opinion on where it's applied; callers are responsible for keeping it out
of header code paths.
"""
from __future__ import annotations

import re

_MARKER = "«redacted-secret»"

# Most-specific first: e.g. an Anthropic key must be consumed whole by its own
# pattern before the generic trailing `sk-...` pattern ever gets a chance to
# see it (sequential substitution means an already-replaced marker no longer
# contains the literal prefix a later, looser pattern is looking for).
_PATTERNS = [
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.DOTALL),  # PEM
    re.compile(r"eyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"),  # JWT
    re.compile(r"sk-ant-[A-Za-z0-9_-]{20,}"),   # Anthropic
    re.compile(r"sk-proj-[A-Za-z0-9_-]{20,}"),  # OpenAI project key
    re.compile(r"gsk_[A-Za-z0-9]{20,}"),        # Groq
    re.compile(r"gh[posru]_[A-Za-z0-9]{36,}"),  # GitHub PAT/OAuth
    re.compile(r"AKIA[0-9A-Z]{16}"),            # AWS access key id
    re.compile(r"AIza[0-9A-Za-z_-]{35}"),       # Google API key
    re.compile(r"xox[baprs]-[0-9A-Za-z-]{10,}"),  # Slack
    re.compile(r"sk-[A-Za-z0-9]{20,}"),         # OpenAI / generic sk- (LAST: least specific)
]


def redact_secrets(text: str) -> tuple[str, int]:
    """Replace every known secret-shaped substring in `text` with a fixed
    marker. Returns (redacted_text, num_redactions).

    Best-effort by contract: NEVER raises. A bug in this function must never
    turn into a broken outbound request, so any failure (including `text` not
    actually being a string) degrades to a no-op -- the original value back,
    zero redactions -- rather than propagating."""
    try:
        if not isinstance(text, str) or not text:
            return text, 0
        total = 0
        for pattern in _PATTERNS:
            text, count = pattern.subn(_MARKER, text)
            total += count
        return text, total
    except Exception:
        return text, 0


def redact_obj(obj):
    """Recursively return a COPY of a JSON-ish structure (dict/list/str/other)
    with every string value passed through `redact_secrets`. Returns
    (new_obj, total_count). Used for MCP tool args, so nested arrays/objects
    (e.g. a coerced JSON payload) are covered, not just top-level strings.
    Non-string scalars (int/float/bool/None/...) pass through unchanged."""
    if isinstance(obj, dict):
        total = 0
        new_dict: dict = {}
        for key, value in obj.items():
            new_value, count = redact_obj(value)
            new_dict[key] = new_value
            total += count
        return new_dict, total
    if isinstance(obj, list):
        total = 0
        new_list: list = []
        for item in obj:
            new_item, count = redact_obj(item)
            new_list.append(new_item)
            total += count
        return new_list, total
    if isinstance(obj, str):
        return redact_secrets(obj)
    return obj, 0
