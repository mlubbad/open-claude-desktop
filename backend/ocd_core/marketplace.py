"""Plugin marketplace — browse a catalog and install plugins into the user's plugins
dir (from which the runtime loads them as agent tools).

Two catalog sources feed it:

* the **bundled** catalog (``MARKETPLACE_DIR``) — vetted plugins that ship with the
  app; and
* user-added **repository sources** — git repos the user syncs from a URL. This runs
  third-party plugin CODE on the machine, so it is guarded: it only happens on an
  explicit user action (the desktop app shows a warning), can be hard-disabled with
  ``MARKETPLACE_ALLOW_REMOTE=0``, clones are shallow + size/time-capped, and installs
  are path-jailed to ``PLUGINS_DIR``.

``install`` only ever copies a catalog file (bundled or from a synced source) into
``PLUGINS_DIR`` and then verifies it loads as a real plugin; ``uninstall`` only ever
removes a file that a current catalog entry maps to — so a built-in that ships in
``PLUGINS_DIR`` but is in no catalog can never be deleted through the marketplace.
"""
from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from . import config, integrations, jsonstore

_META = {
    "name": re.compile(r'^NAME\s*=\s*["\'](.+?)["\']', re.M),
    "description": re.compile(r'^DESCRIPTION\s*=\s*["\'](.+?)["\']', re.M),
    "category": re.compile(r'^CATEGORY\s*=\s*["\'](.+?)["\']', re.M),
}
# A plugin file textually defines a TOOL schema and a run() entrypoint. Checked by
# regex (never by importing) so listing an untrusted repo executes none of its code.
_HAS_TOOL = re.compile(r'^\s*TOOL\s*=', re.M)
_HAS_RUN = re.compile(r'^\s*def\s+run\s*\(', re.M)

_MAX_PLUGIN_BYTES = 256 * 1024   # per-file cap when scanning a synced repo
_MAX_SOURCE_PLUGINS = 100        # per-source cap on discovered plugins
_MAX_SCAN_FILES = 20000          # per-source cap on .py files examined during discovery


# --------------------------------------------------------------------------- #
#  Shared helpers
# --------------------------------------------------------------------------- #
def _dir() -> Path:
    return Path(config.MARKETPLACE_DIR)


def _meta(text: str, stem: str) -> dict:
    def grab(key: str, default: str) -> str:
        m = _META[key].search(text)
        return m.group(1) if m else default
    return {"name": grab("name", stem), "description": grab("description", ""),
            "category": grab("category", "Utility")}


def _looks_like_plugin(text: str) -> bool:
    return bool(_HAS_TOOL.search(text) and _HAS_RUN.search(text))


def _catalog_files() -> list[Path]:
    d = _dir()
    if not d.is_dir():
        return []
    return [f for f in sorted(d.glob("*.py")) if not f.name.startswith("_")]


# --------------------------------------------------------------------------- #
#  Repository sources (synced from a git URL)
# --------------------------------------------------------------------------- #
def remote_allowed() -> bool:
    return bool(config.MARKETPLACE_ALLOW_REMOTE)


def _sources_dir() -> Path:
    return Path(config.MARKETPLACE_SOURCES_DIR)


def _sources_file() -> Path:
    return Path(config.MARKETPLACE_SOURCES_FILE)


def _load_sources() -> list[dict]:
    return jsonstore.load_json(_sources_file(), [])


def _save_sources(sources: list[dict]) -> None:
    # Atomic replace so a crash mid-write can't corrupt/truncate the registry.
    jsonstore.save_json(_sources_file(), sources)


def _source_id(url: str) -> str:
    return "mp" + hashlib.sha1(url.strip().encode("utf-8")).hexdigest()[:10]


def _valid_git_url(url: str) -> bool:
    """Accept only https:// and the git@host:path SSH form; reject plaintext transports
    (http://, git://), local paths (file://, bare paths), and anything with
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


def _repo_name(url: str) -> str:
    tail = re.split(r'[/:]', url.strip().rstrip("/"))[-1]
    return re.sub(r'\.git$', '', tail) or "repository"


def _clone_repo(url: str, ref: str, dest: Path) -> None:
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


def _dir_size(root: Path) -> int:
    total = 0
    for p in root.rglob("*"):
        if p.is_file() and not p.is_symlink():
            try:
                total += p.stat().st_size
            except OSError:
                pass
    return total


def _discover(root: Path) -> list[Path]:
    """Plugin files inside a synced repo — .py files that textually look like plugins.
    Skips .git, dotfiles, underscore-prefixed and oversized files; both the number of
    plugins kept and the number of files scanned are capped so a repo with a huge file
    tree can't make discovery expensive."""
    found: list[Path] = []
    scanned = 0
    for f in root.rglob("*.py"):
        scanned += 1
        if scanned > _MAX_SCAN_FILES or len(found) >= _MAX_SOURCE_PLUGINS:
            break
        rel = f.relative_to(root)
        if any(part.startswith((".", "_")) for part in rel.parts):
            continue
        if f.is_symlink() or not f.is_file():
            continue
        try:
            if f.stat().st_size > _MAX_PLUGIN_BYTES:
                continue
            text = f.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if _looks_like_plugin(text):
            found.append(f)
    return sorted(found)


def list_sources() -> list[dict]:
    """The synced repository sources, each with a live count of the plugins it exposes."""
    out = []
    for s in _load_sources():
        d = _sources_dir() / s["id"]
        out.append({
            "id": s["id"],
            "name": s.get("name", _repo_name(s.get("url", ""))),
            "url": s.get("url", ""),
            "ref": s.get("ref", ""),
            "added_at": s.get("added_at", ""),
            "plugins": len(_discover(d)) if d.is_dir() else 0,
            "present": d.is_dir(),
        })
    return out


def add_source(url: str, ref: str = "", name: str = "") -> dict:
    """Sync a git repo as a marketplace source: clone it, then expose the plugins it
    contains as installable catalog entries. Re-adding the same URL re-syncs it."""
    if not _valid_git_url(url):
        return {"ok": False, "detail": "not a valid git URL (use https:// or git@…)"}
    sid = _source_id(url)
    existing = _load_sources()
    if not any(s.get("id") == sid for s in existing) and len(existing) >= config.MARKETPLACE_MAX_SOURCES:
        return {"ok": False, "detail": f"source limit reached ({config.MARKETPLACE_MAX_SOURCES})"}
    dest = _sources_dir() / sid
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        shutil.rmtree(dest, ignore_errors=True)
    try:
        _clone_repo(url, ref, dest)
    except RuntimeError as e:
        shutil.rmtree(dest, ignore_errors=True)
        return {"ok": False, "detail": f"could not sync: {e}"}
    if _dir_size(dest) > config.MARKETPLACE_MAX_SOURCE_BYTES:
        shutil.rmtree(dest, ignore_errors=True)
        return {"ok": False, "detail": "repository is too large"}
    plugins = _discover(dest)
    if not plugins:
        shutil.rmtree(dest, ignore_errors=True)
        return {"ok": False, "detail": "no plugins found in this repository"}
    entry = {
        "id": sid,
        "name": (name.strip() or _repo_name(url)),
        "url": url.strip(),
        "ref": ref.strip(),
        "added_at": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    sources = [s for s in _load_sources() if s.get("id") != sid]
    sources.append(entry)
    _save_sources(sources)
    return {"ok": True, "source": {**entry, "plugins": len(plugins), "present": True}}


def remove_source(sid: str) -> dict:
    """Drop a synced source: uninstall the plugins it contributed and delete its clone."""
    sources = _load_sources()
    if not any(s.get("id") == sid for s in sources):
        return {"ok": False, "detail": "unknown source"}
    # Remove any installed plugin files this source contributed (dest names are prefixed).
    dest_dir = Path(integrations.PLUGINS_DIR).resolve()
    if dest_dir.is_dir():
        for f in dest_dir.glob(f"{sid}__*.py"):
            rf = f.resolve()
            if rf.parent == dest_dir:
                rf.unlink(missing_ok=True)
    shutil.rmtree(_sources_dir() / sid, ignore_errors=True)
    _save_sources([s for s in sources if s.get("id") != sid])
    return {"ok": True}


# --------------------------------------------------------------------------- #
#  Unified catalog (bundled + sources) and install / uninstall
# --------------------------------------------------------------------------- #
def _entries() -> list[dict]:
    """Every installable plugin, from the bundled catalog and every synced source.

    Each entry carries an internal ``path`` (the catalog file to copy) and ``dest`` (the
    filename it installs AS inside PLUGINS_DIR). Bundled entries keep their own filename;
    source entries are namespaced ``<sourceid>__<stem>_<hash>.py`` so sources never
    collide. Names are deduped (first wins, bundled before sources), so a synced source
    can neither shadow nor duplicate an existing catalog name — install/uninstall by
    name is therefore deterministic and always targets the row the UI shows.
    """
    entries: list[dict] = []
    seen: set[str] = set()

    def _add(entry: dict) -> None:
        if entry["name"] in seen:
            return
        seen.add(entry["name"])
        entries.append(entry)

    for f in _catalog_files():
        try:
            meta = _meta(f.read_text(encoding="utf-8"), f.stem)
        except OSError:
            continue
        _add({**meta, "origin": "bundled", "source_id": None, "path": f, "dest": f.name})
    for s in _load_sources():
        d = _sources_dir() / s["id"]
        if not d.is_dir():
            continue
        for f in _discover(d):
            try:
                meta = _meta(f.read_text(encoding="utf-8"), f.stem)
            except OSError:
                continue
            # 48-bit tag keyed on the repo-relative path: collision-resistant across a
            # source's plugins so two files never map to the same install filename.
            tag = hashlib.sha1(str(f.relative_to(d)).encode()).hexdigest()[:12]
            _add({**meta, "origin": s.get("name", _repo_name(s.get("url", ""))),
                  "source_id": s["id"], "path": f, "dest": f"{s['id']}__{f.stem}_{tag}.py"})
    return entries


def _entry_by_name(name: str) -> dict | None:
    for e in _entries():
        if e["name"] == name:
            return e
    return None


def catalog() -> list[dict]:
    """The available plugins, each flagged whether it's already installed."""
    installed = {p["name"] for p in integrations.list_plugins()}
    out = []
    for e in _entries():
        out.append({"name": e["name"], "description": e["description"],
                    "category": e["category"], "origin": e["origin"],
                    "source_id": e["source_id"], "installed": e["name"] in installed})
    return out


def install(name: str) -> dict:
    """Copy a catalog plugin (bundled or synced) into PLUGINS_DIR, then verify it loads."""
    entry = _entry_by_name(name)
    if entry is None:
        return {"ok": False, "name": name, "detail": "not in the marketplace"}
    dest_dir = Path(integrations.PLUGINS_DIR)
    dest_dir.mkdir(parents=True, exist_ok=True)
    dst = (dest_dir.resolve() / entry["dest"]).resolve()
    # Defensive path jail (mirrors uninstall): the install target must sit directly
    # inside PLUGINS_DIR, so a future change to how `dest` is derived can't traverse out.
    if dst.parent != dest_dir.resolve():
        return {"ok": False, "name": name, "detail": "refused: path outside plugins dir"}
    try:
        shutil.copyfile(entry["path"], dst)
    except OSError as e:
        return {"ok": False, "name": name, "detail": f"could not install: {e}"}
    mod = integrations._load_plugin_module(dst)
    if not (mod and hasattr(mod, "TOOL") and hasattr(mod, "run")):
        dst.unlink(missing_ok=True)
        return {"ok": False, "name": name, "detail": "plugin failed to load"}
    return {"ok": True, "name": name, "installed": True}


def uninstall(name: str) -> dict:
    """Remove a previously-installed CATALOG plugin from PLUGINS_DIR (never a built-in)."""
    entry = _entry_by_name(name)
    if entry is None:
        return {"ok": False, "name": name, "detail": "not a marketplace plugin"}
    dest_dir = Path(integrations.PLUGINS_DIR).resolve()
    dst = (dest_dir / entry["dest"]).resolve()
    # Defensive path jail: the target must sit directly inside PLUGINS_DIR.
    if dst.parent != dest_dir:
        return {"ok": False, "name": name, "detail": "refused: path outside plugins dir"}
    if dst.exists():
        dst.unlink()
    return {"ok": True, "name": name, "installed": False}
