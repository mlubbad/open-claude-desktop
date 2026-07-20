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


def canonical_key(root, user_path) -> str:
    """A stable per-file identity for read-tracking (real path, posix, case-folded)."""
    target = resolve_in_workspace(root, user_path)
    return target.as_posix().casefold()


def write_file(root, user_path, content: str, read_paths: set):
    """Create or overwrite a file. Overwriting an existing file requires it to have been
    read this turn (its key present in ``read_paths``) — Claude Code's anti-clobber guard.
    On success the file's key is added to ``read_paths`` (a write implies you now know it)."""
    try:
        target = resolve_in_workspace(root, user_path)
        key = target.as_posix().casefold()
    except JailError:
        return _err("path is outside the workspace")
    if target.exists() and key not in read_paths:
        return _err("must read the file before overwriting it (call read_file first)")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    read_paths.add(key)
    return _ok(path=user_path, bytes=len(content.encode("utf-8")))
