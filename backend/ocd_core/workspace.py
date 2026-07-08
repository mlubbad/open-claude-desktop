"""Code workspace — read-only views of the per-project sandbox the agent's file tools
edit.

The `text_editor` / `bash` / `code_execution` tools are jailed to
``SANDBOX_ROOT/<project>`` (see integrations). The desktop **Code** tab renders that same
directory: a file tree and file contents. Everything here is read-only and
traversal-jailed — the agent writes, this module only shows.
"""
from __future__ import annotations

from pathlib import Path

from . import integrations

# Directories that only add noise to a code workspace tree.
_IGNORE_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", ".mypy_cache",
                ".pytest_cache", ".ruff_cache", "dist", "build", ".next", "target",
                ".exec"}  # code_execution's transient script scratch dir


def workspace_root(project: str | None) -> Path:
    """The on-disk workspace directory for a project (created on demand). The project id
    is reduced to a safe slug segment so a crafted ``project=../../..`` can't escape
    SANDBOX_ROOT (the tree/file/download routes all resolve paths under this root)."""
    root = integrations.SANDBOX_ROOT / integrations.safe_project(project)
    root.mkdir(parents=True, exist_ok=True)
    return root


def list_tree(project: str | None, max_entries: int = 4000) -> list[dict]:
    """A flat, sorted list of ``{path, type, size}`` (posix relative paths) for the
    workspace, skipping noisy build/vendor dirs. Directories precede their contents by
    sort order, so the client can render a tree."""
    root = workspace_root(project)
    out: list[dict] = []
    for p in sorted(root.rglob("*"), key=lambda x: x.relative_to(root).as_posix()):
        rel_parts = p.relative_to(root).parts
        if any(part in _IGNORE_DIRS for part in rel_parts):
            continue
        is_dir = p.is_dir()
        out.append({"path": p.relative_to(root).as_posix(),
                    "type": "dir" if is_dir else "file",
                    "size": (p.stat().st_size if p.is_file() else 0)})
        if len(out) >= max_entries:
            break
    return out


def file_path(project: str | None, relpath: str) -> Path | None:
    """The absolute on-disk path for a workspace file, traversal-jailed. Returns None if
    the path escapes the workspace or isn't an existing file (used by the download route)."""
    root = workspace_root(project)
    target = integrations._jail_path(root, relpath)
    if target is None or not target.is_file():
        return None
    return target


def read_file(project: str | None, relpath: str, max_bytes: int = 400_000) -> dict:
    """Read a workspace file (traversal-jailed). Returns ``{path, content, binary, size,
    truncated}`` or ``{error}``. Binary files return no content."""
    root = workspace_root(project)
    target = integrations._jail_path(root, relpath)
    if target is None:
        return {"error": "path not allowed"}
    if not target.is_file():
        return {"error": "not a file"}
    data = target.read_bytes()
    truncated = len(data) > max_bytes
    data = data[:max_bytes]
    try:
        text = data.decode("utf-8")
        binary = False
    except UnicodeDecodeError:
        text = ""
        binary = True
    return {"path": target.relative_to(root).as_posix(), "content": text,
            "binary": binary, "size": target.stat().st_size, "truncated": truncated}
