"""Workspace path jail + file-tool implementations.

The jail resolves the *real* path (symlinks/junctions followed) and requires it to
lie at or under the real workspace root. Unlike the legacy string-prefix jail in
integrations.py, this defeats symlink/junction escapes and sibling-prefix roots
(C:\\ws vs C:\\ws2). Pure and exhaustively unit-testable.
"""
from __future__ import annotations

from pathlib import Path


class JailError(Exception):
    """Raised when a user-supplied path escapes the workspace root."""


def resolve_in_workspace(root: Path, user_path: str) -> Path:
    """Resolve ``user_path`` (workspace-relative) to a real absolute path under ``root``.

    Raises ``JailError`` on any escape (parent traversal, absolute path outside,
    symlink/junction that points out, sibling-prefix root). An empty path resolves to
    the root itself. A leading-absolute path (``/etc/passwd``, ``C:/Windows``) is
    rejected — the model must use workspace-relative paths.
    """
    root_real = Path(root).resolve()
    raw = (user_path or "").strip().replace("\\", "/")
    if raw.startswith("workspace/"):
        raw = raw[len("workspace/"):]
    if raw in ("", "."):
        return root_real
    real = (root_real / raw).resolve(strict=False)  # follows symlinks; collapses .. ; tolerates non-existent tail
    try:
        real.relative_to(root_real)
    except ValueError:
        raise JailError(f"path escapes workspace: {user_path!r}") from None
    return real


MAX_READ_LINES = 2000
MAX_LINE_CHARS = 2000


def _ok(**kw):
    return {"ok": True, **kw}


def _err(msg: str):
    return {"ok": False, "error": msg}


def read_file(root, user_path, offset: int = 1, limit: int = MAX_READ_LINES):
    """Read a text file, returning cat -n style numbered lines from ``offset`` (1-based)."""
    try:
        target = resolve_in_workspace(root, user_path)
    except JailError:
        return _err("path is outside the workspace")
    if not target.is_file():
        return _err(f"file not found: {user_path}")
    try:
        data = target.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return _err("file is not UTF-8 text")
    lines = data.splitlines()
    start = max(1, offset)
    chunk = lines[start - 1: start - 1 + max(1, limit)]
    numbered = []
    for i, line in enumerate(chunk, start=start):
        if len(line) > MAX_LINE_CHARS:
            line = line[:MAX_LINE_CHARS] + "…[truncated]"
        numbered.append(f"{i}\t{line}")
    return _ok(content="\n".join(numbered), path=target.name,
               total_lines=len(lines), shown=len(chunk))
