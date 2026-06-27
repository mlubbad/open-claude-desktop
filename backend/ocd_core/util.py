"""Pure, dependency-free helpers shared by both app surfaces.

Ported verbatim from aj360_app/aj360_app/core.py so the FastAPI backend and the
Reflex frontend share one implementation. Behavior parity is the contract — do
NOT "improve" the logic here; change the call sites instead if behavior must
evolve.

Public names: slugify, fmt_bytes, relative_time, format_date, chunk_id,
flatten_fields. Private back-compat aliases (_slugify, _fmt_size/_fmt_bytes,
_chunk_id, _flatten_fields) match the original names so existing call sites keep
working unchanged.
"""
from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone


def slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug or "untitled"


def fmt_bytes(n) -> str:
    if not n:
        return "0 B"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.1f} {unit}"
        n /= 1024


def fmt_size(n: int) -> str:
    return f"{n // 1024} KB" if n < 1024 * 1024 else f"{n / (1024 * 1024):.1f} MB"


def chunk_id(filename: str, idx: int, content: str) -> str:
    h = hashlib.sha256(f"{filename}:{idx}:{content[:500]}".encode()).hexdigest()[:20]
    return f"{filename}_{idx}_{h}"


def flatten_fields(fields, prefix=""):
    out = []
    for f in fields:
        name = f"{prefix}{f.name}"
        out.append((name, f.field_type, f.mode or "NULLABLE"))
        if f.field_type == "RECORD" and f.fields:
            out.extend(flatten_fields(f.fields, prefix=name + "."))
    return out


def format_date(iso_str: str) -> str:
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        return f"{dt.strftime('%b')} {dt.day}"
    except Exception:
        return "Recently"


def relative_time(value) -> str:
    try:
        if isinstance(value, str):
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        elif isinstance(value, (int, float)):
            dt = datetime.fromtimestamp(value, tz=timezone.utc)
        else:
            dt = value
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        secs = (datetime.now(timezone.utc) - dt).total_seconds()
        if secs < 60:
            return "just now"
        if secs < 3600:
            m = int(secs // 60)
            return f"{m} minute{'s' if m != 1 else ''} ago"
        if secs < 86400:
            h = int(secs // 3600)
            return f"{h} hour{'s' if h != 1 else ''} ago"
        days = int(secs // 86400)
        if days == 1:
            return "yesterday"
        if days < 7:
            return f"{days} days ago"
        if days < 30:
            return f"{days // 7} week{'s' if days // 7 != 1 else ''} ago"
        if days < 365:
            return f"{days // 30} month{'s' if days // 30 != 1 else ''} ago"
        return f"{days // 365} year{'s' if days // 365 != 1 else ''} ago"
    except Exception:
        return "recently"


# Back-compat private aliases matching the original core.py names so existing
# call sites (e.g. core._slugify, core._fmt_size, core._chunk_id,
# core._flatten_fields) keep working after they import from here.
_slugify = slugify
_fmt_size = _fmt_bytes = fmt_size
_chunk_id = chunk_id
_flatten_fields = flatten_fields
