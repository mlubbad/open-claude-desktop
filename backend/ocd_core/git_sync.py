"""Shared git-sync primitives: validate a repo URL, derive a name, shallow-clone it,
and measure a checkout's size.

Extracted from ``marketplace`` so both the plugin marketplace AND the skills importer
depend on this leaf module instead of ``skills`` reaching into ``marketplace``'s
private helpers (which forced a lazy import "to avoid a module-load cycle"). Nothing
here executes a cloned repo's code — cloning only fetches data; running third-party
code happens only on an explicit install, in the caller.
"""
from __future__ import annotations

import contextlib
import os
import re
import shutil
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


def clone_error_detail(stderr: bytes | str | None) -> str:
    """Distill git's stderr into one actionable message.

    git explains failures across several lines — e.g. the SSH-transport failure
        fatal: Could not read from remote repository.
        Please make sure you have the correct access rights
        and the repository exists.
    Reporting only the last line (the old behavior) produced nonsense fragments like
    "and the repository exists." with the actual reason thrown away. Keep the tail of
    the real message and, for the failure shapes users actually hit, append what to DO
    about it."""
    text = stderr.decode("utf-8", "replace") if isinstance(stderr, bytes) else (stderr or "")
    lines = [ln.strip() for ln in text.strip().splitlines()
             if ln.strip() and not ln.strip().startswith("Cloning into")]
    msg = " ".join(lines[-4:])[:400] or "git clone failed"
    low = msg.lower()
    if "could not read from remote repository" in low or "correct access rights" in low:
        msg += (" — git switched to SSH or needs credentials for this URL. A global git "
                "config rewrite (url.…insteadOf) or credential helper on this machine is "
                "likely intercepting it; run `git clone <url>` in a terminal to see the "
                "full error.")
    elif "terminal prompts disabled" in low or "authentication failed" in low:
        msg += (" — the repository seems to require sign-in (is it private?). Use a "
                "public URL, or set up a git credential helper for this host.")
    elif "remote branch" in low and "not found" in low:
        msg += " — leave the branch field empty to use the repository's default branch."
    elif "could not resolve host" in low or "unable to access" in low:
        msg += " — check the network/proxy connection and that the URL is correct."
    return msg


# The file types plugin/skill discovery actually reads: Python plugins, markdown
# skills (SKILL.md included), and manifests. The text-only checkout below materializes
# ONLY these, so a repo full of images/datasets/site assets doesn't get downloaded at
# all — that's what made real-world repos blow the size cap ("repository is too
# large" for a 218 MB prompt-collection repo whose useful text was a few MB).
TEXT_PATTERNS = ("*.py", "*.md", "*.markdown", "*.json", "*.yaml", "*.yml", "*.toml")


def clone_repo(url: str, ref: str, dest: Path) -> None:
    """Fetch the TEXT of ``url`` into ``dest``. Isolated here so tests can monkeypatch it.

    Primary path is a partial clone (``--filter=blob:limit=512k --no-checkout``)
    followed by a checkout of just TEXT_PATTERNS. The blob filter keeps large binaries
    (images, datasets, archives) off the wire while every small blob arrives in the
    single initial pack — so the pattern checkouts are local, not one lazy network
    fetch per file (blob:none degenerated into hundreds of serial round-trips). If the
    fancy path fails (an old git, a server without partial-clone support), it falls
    back to the plain shallow clone.

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
    base = ["git", "clone", "--depth", "1", "--no-tags", "--single-branch"]
    if ref.strip():
        base += ["--branch", ref.strip()]
    tail = ["--", url, str(dest)]
    env = dict(os.environ)
    env["GIT_TERMINAL_PROMPT"] = "0"      # fail fast instead of hanging for a password
    env.setdefault("GIT_LFS_SKIP_SMUDGE", "1")  # don't pull large LFS blobs on checkout

    def _run(cmd: list[str]) -> None:
        subprocess.run(cmd, env=env, check=True, capture_output=True,
                       timeout=config.MARKETPLACE_CLONE_TIMEOUT_SEC)

    try:
        try:
            _run(base + ["--filter=blob:limit=512k", "--no-checkout"] + tail)
            for pattern in TEXT_PATTERNS:
                # Each pattern separately: a repo with no *.py must still get its *.md.
                # (git exits non-zero when a pathspec matches nothing — that's fine.)
                with contextlib.suppress(subprocess.CalledProcessError):
                    _run(["git", "-C", str(dest), "checkout", "HEAD", "--", pattern])
        except subprocess.CalledProcessError:
            # Partial clone unsupported somewhere in the chain — plain shallow clone.
            shutil.rmtree(dest, ignore_errors=True)
            _run(base + tail)
    except FileNotFoundError as e:
        raise RuntimeError("git is not installed on this machine") from e
    except subprocess.TimeoutExpired as e:
        raise RuntimeError("clone timed out") from e
    except subprocess.CalledProcessError as e:
        raise RuntimeError(clone_error_detail(e.stderr)) from e


def dir_size(root: Path) -> int:
    """Size of the checkout's CONTENT — `.git` is packfile metadata the scanners never
    read, and counting it silently halved the effective size budget."""
    total = 0
    for p in root.rglob("*"):
        if ".git" in p.parts:
            continue
        if p.is_file() and not p.is_symlink():
            try:
                total += p.stat().st_size
            except OSError:
                pass
    return total
