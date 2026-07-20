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
    the root itself.
    """
    root_real = Path(root).resolve()
    raw = (user_path or "").strip().replace("\\", "/").lstrip("/")
    # strip accidental workspace/ prefixes the model sometimes adds
    for prefix in ("workspace/",):
        if raw.startswith(prefix):
            raw = raw[len(prefix):]
    if raw in ("", "."):
        return root_real
    candidate = (root_real / raw)
    # Resolve the deepest existing ancestor so we follow real symlinks, then re-attach
    # the not-yet-created tail (for write/create of new files).
    real = _resolve_existing_prefix(candidate)
    try:
        real.relative_to(root_real)
    except ValueError:
        raise JailError(f"path escapes workspace: {user_path!r}")
    return real


def _resolve_existing_prefix(path: Path) -> Path:
    """Path.resolve() but tolerant of a non-existent tail: resolve the longest existing
    ancestor (following symlinks), then re-append the remaining segments. This makes the
    jail correct for files that don't exist yet (write_file/create) while still catching
    a symlinked *directory* in the middle of the path."""
    path = Path(path)
    parts = path.parts
    for i in range(len(parts), 0, -1):
        head = Path(*parts[:i])
        if head.exists():
            resolved_head = head.resolve()
            tail = parts[i:]
            return resolved_head.joinpath(*tail) if tail else resolved_head
    # Nothing exists (e.g. root itself missing) — resolve lexically.
    return path.resolve()
