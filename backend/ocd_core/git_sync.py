"""Shared git-sync primitives: validate a repo URL, derive a name, shallow-clone it,
and measure a checkout's size.

Extracted from ``marketplace`` so both the plugin marketplace AND the skills importer
depend on this leaf module instead of ``skills`` reaching into ``marketplace``'s
private helpers (which forced a lazy import "to avoid a module-load cycle"). Nothing
here executes a cloned repo's code — cloning only fetches data; running third-party
code happens only on an explicit install, in the caller.
"""
from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

from . import config


def valid_git_url(url: str) -> bool:
    """Accept only ``https://`` and the ``git@host:path`` SSH form; reject plaintext
    transports (http://, git://), local paths (file://, bare paths), and anything with
    whitespace/control chars. Since a synced repo's code is later executed on install,
    we refuse MITM-prone plaintext transports up front."""
    u = (url or "").strip()
    if not u or any(c.isspace() for c in u) or any(ord(c) < 32 for c in u):
        return False
    if re.match(r'^https://[^/].+', u):
        return True
    if re.match(r'^[\w.+-]+@[\w.-]+:.+', u):   # scp-style ssh: git@github.com:owner/repo.git
        return True
    return False


def repo_name(url: str) -> str:
    tail = re.split(r'[/:]', url.strip().rstrip("/"))[-1]
    return re.sub(r'\.git$', '', tail) or "repository"


def clone_repo(url: str, ref: str, dest: Path) -> None:
    """Shallow-clone ``url`` into ``dest``. Isolated here so tests can monkeypatch it.

    Never fetches submodules, never blocks on an interactive prompt, and is time-bounded.
    Inherits the caller's environment so proxy settings (HTTPS_PROXY), the CA bundle,
    HOME/git-config, credential helpers, and loader paths all apply — a hand-built
    minimal env silently breaks cloning behind a proxy (``getaddrinfo() thread failed to
    start``) or with a non-standard git. Raises RuntimeError with a clean message on
    any failure. Cloning only fetches data; git does not execute a remote repo's hooks,
    so passing the real environment here is safe (repo code runs only on install).
    """
    # NOTE: we deliberately do NOT pin protocol.http.allow=never. Proxy setups (incl.
    # this app's own agent proxy) route git via a gitconfig `insteadOf` rule that rewrites
    # https://github.com/ to a plaintext http:// proxy URL — blocking http would break
    # cloning behind a proxy. The residual "a machine's gitconfig could downgrade the URL"
    # risk is low, not attacker-injectable, and no worse than any tool running git here.
    cmd = ["git", "clone", "--depth", "1", "--no-tags", "--single-branch"]
    if ref.strip():
        cmd += ["--branch", ref.strip()]
    cmd += ["--", url, str(dest)]
    env = dict(os.environ)
    env["GIT_TERMINAL_PROMPT"] = "0"      # fail fast instead of hanging for a password
    env.setdefault("GIT_LFS_SKIP_SMUDGE", "1")  # don't pull large LFS blobs on checkout
    try:
        subprocess.run(cmd, env=env, check=True, capture_output=True,
                       timeout=config.MARKETPLACE_CLONE_TIMEOUT_SEC)
    except FileNotFoundError as e:
        raise RuntimeError("git is not installed on this machine") from e
    except subprocess.TimeoutExpired as e:
        raise RuntimeError("clone timed out") from e
    except subprocess.CalledProcessError as e:
        detail = (e.stderr or b"").decode("utf-8", "replace").strip().splitlines()
        raise RuntimeError(detail[-1] if detail else "git clone failed") from e


def dir_size(root: Path) -> int:
    total = 0
    for p in root.rglob("*"):
        if p.is_file() and not p.is_symlink():
            try:
                total += p.stat().st_size
            except OSError:
                pass
    return total
