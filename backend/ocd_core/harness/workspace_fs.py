"""Workspace path jail + file-tool implementations.

The jail resolves the *real* path (symlinks/junctions followed) and requires it to
lie at or under the real workspace root. Unlike the legacy string-prefix jail in
integrations.py, this defeats symlink/junction escapes and sibling-prefix roots
(C:\\ws vs C:\\ws2). Pure and exhaustively unit-testable.
"""
from __future__ import annotations

import difflib
import re
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


def edit_file(root, user_path, old_string: str, new_string: str,
              replace_all: bool = False, read_paths: set | None = None):
    """Replace ``old_string`` with ``new_string`` in a file. Fails unless the file was
    read this turn, and (unless ``replace_all``) unless ``old_string`` occurs exactly once.
    Returns a unified diff on success."""
    read_paths = read_paths if read_paths is not None else set()
    try:
        target = resolve_in_workspace(root, user_path)
        key = target.as_posix().casefold()
    except JailError:
        return _err("path is outside the workspace")
    if not target.is_file():
        return _err(f"file not found: {user_path}")
    if key not in read_paths:
        return _err("must read the file before editing it (call read_file first)")
    before = target.read_text(encoding="utf-8")
    count = before.count(old_string)
    if count == 0:
        return _err(f"old_string not found in {user_path}")
    if count > 1 and not replace_all:
        return _err(f"old_string is not unique ({count} matches); add context or set replace_all")
    after = (before.replace(old_string, new_string) if replace_all
             else before.replace(old_string, new_string, 1))
    target.write_text(after, encoding="utf-8")
    diff = "\n".join(difflib.unified_diff(
        before.splitlines(), after.splitlines(),
        fromfile=user_path, tofile=user_path, lineterm=""))
    return _ok(path=user_path, replacements=(count if replace_all else 1), diff=diff)


_IGNORE_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv",
                ".mypy_cache", ".pytest_cache", ".ruff_cache", "dist", "build",
                ".next", "target"}
MAX_GLOB = 500
MAX_GREP_MATCHES = 300


def _iter_files(root):
    for p in sorted(root.rglob("*")):
        rel = p.relative_to(root)
        if any(part in _IGNORE_DIRS for part in rel.parts):
            continue
        if p.is_file():
            yield p, rel


def glob(root, pattern: str, max_results: int = MAX_GLOB):
    root_real = resolve_in_workspace(root, "")
    hits = []
    for p in sorted(root_real.glob(pattern), key=lambda x: (x.is_dir(), x.name)):
        rel = p.relative_to(root_real)
        if any(part in _IGNORE_DIRS for part in rel.parts):
            continue
        hits.append(rel.as_posix())
    truncated = len(hits) > max_results
    return _ok(paths=hits[:max_results], truncated=truncated)


def grep(root, pattern: str, path: str = "", mode: str = "content",
         max_matches: int = MAX_GREP_MATCHES):
    try:
        base = resolve_in_workspace(root, path)
    except JailError:
        return _err("path is outside the workspace")
    try:
        rx = re.compile(pattern)
    except re.error as e:
        return _err(f"bad regex: {e}")
    root_real = resolve_in_workspace(root, "")
    scan_root = base if base.is_dir() else base.parent
    matches, files = [], []
    for p, _rel in _iter_files(scan_root):
        try:
            text = p.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        relp = p.relative_to(root_real).as_posix()
        found = False
        for ln, line in enumerate(text.splitlines(), start=1):
            if rx.search(line):
                found = True
                if mode == "content" and len(matches) < max_matches:
                    matches.append(f"{relp}:{ln}:{line.strip()[:300]}")
        if found:
            files.append(relp)
    if mode == "files":
        return _ok(files=files[:max_matches], count=len(files))
    if mode == "count":
        return _ok(count=len(matches))
    return _ok(matches=matches, truncated=len(matches) >= max_matches)


FILE_TOOL_SPECS = [
    {"type": "function", "function": {
        "name": "read_file",
        "description": "Read a text file from the workspace. Returns cat -n style "
                       "line-numbered content. Always read a file before editing or "
                       "overwriting it.",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string", "description": "Workspace-relative file path."},
            "offset": {"type": "integer", "description": "1-based first line (default 1)."},
            "limit": {"type": "integer", "description": "Max lines to return (default 2000)."}},
            "required": ["path"]}}},
    {"type": "function", "function": {
        "name": "edit_file",
        "description": "Replace an EXACT unique snippet in a file. old_string must occur "
                       "exactly once unless replace_all is true. Read the file first.",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string"},
            "old_string": {"type": "string", "description": "Exact text to replace (unique)."},
            "new_string": {"type": "string", "description": "Replacement text."},
            "replace_all": {"type": "boolean", "description": "Replace every occurrence."}},
            "required": ["path", "old_string", "new_string"]}}},
    {"type": "function", "function": {
        "name": "write_file",
        "description": "Create a new file or overwrite an existing one. Overwriting "
                       "requires reading the file first.",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string"},
            "content": {"type": "string"}},
            "required": ["path", "content"]}}},
    {"type": "function", "function": {
        "name": "glob",
        "description": "List workspace files matching a glob pattern (e.g. **/*.py).",
        "parameters": {"type": "object", "properties": {
            "pattern": {"type": "string"}},
            "required": ["pattern"]}}},
    {"type": "function", "function": {
        "name": "grep",
        "description": "Search workspace file contents with a regular expression. "
                       "mode=content|files|count.",
        "parameters": {"type": "object", "properties": {
            "pattern": {"type": "string"},
            "path": {"type": "string", "description": "Optional sub-path to scope the search."},
            "mode": {"type": "string", "enum": ["content", "files", "count"]}},
            "required": ["pattern"]}}},
]


def run_fs_tool(name: str, args: dict, root, read_paths: set) -> dict:
    """Dispatch a file tool by name. Records read paths so edit/write can enforce the
    read-before-modify guard."""
    a = args or {}
    if name == "read_file":
        out = read_file(root, a.get("path", ""), int(a.get("offset", 1) or 1),
                        int(a.get("limit", MAX_READ_LINES) or MAX_READ_LINES))
        if out.get("ok"):
            try:
                read_paths.add(canonical_key(root, a.get("path", "")))
            except JailError:
                pass
        return out
    if name == "edit_file":
        return edit_file(root, a.get("path", ""), a.get("old_string", ""),
                         a.get("new_string", ""), bool(a.get("replace_all")), read_paths)
    if name == "write_file":
        return write_file(root, a.get("path", ""), a.get("content", ""), read_paths)
    if name == "glob":
        return glob(root, a.get("pattern", "*"))
    if name == "grep":
        return grep(root, a.get("pattern", ""), a.get("path", ""), a.get("mode", "content"))
    return _err(f"unknown file tool: {name}")


FILE_TOOL_NAMES = {"read_file", "edit_file", "write_file", "glob", "grep"}
