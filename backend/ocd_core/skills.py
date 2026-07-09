"""Skill discovery + auto-trigger matching (canonical; merges app.py + integrations.py).

Consolidates the two pre-refactor copies into one module while preserving BOTH
behaviors:
  - fenced `---...---` AND bare `key: value` frontmatter (this repo's skills/*.md
    use the bare form; see skills/hero.md);
  - word-boundary trigger matching (no substring false positives);
  - `disabled` skills are skipped;
  - `description` falls back to "Skill" when absent;
  - `file_triggers` (filename substring match) and `references` are exposed.

Returns plain dicts (the integrations.py contract). The dicts are a superset of
the old integrations dicts (they also carry file_triggers + references, mirroring
app.py's Skill object), which is backward-compatible for existing callers.
"""
import json
import re
import shutil
import tempfile
from pathlib import Path

from . import config

_FIELDS = {"name", "description", "auto", "triggers", "file_triggers",
           "disabled", "references"}

# Files written by the user (imported) are tracked here so removal only ever deletes
# a skill the user added — never a bundled one. Sits alongside the skills as a dotfile
# (list_skills globs *.md, so it is never surfaced as a skill).
_IMPORTED_MANIFEST = ".imported.json"
_MAX_SKILL_BYTES = 256 * 1024
_SAFE_STEM = re.compile(r"[^a-zA-Z0-9_.-]+")


def split_frontmatter(raw: str) -> tuple[list[str], str]:
    """Return (frontmatter_lines, body). Supports `---` fences OR bare leading
    `key: value` lines (this repo's skills/*.md use the bare form)."""
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", raw, re.DOTALL)
    if m:
        return m.group(1).splitlines(), m.group(2).strip()
    lines = raw.splitlines()
    front, body_start = [], len(lines)
    for i, line in enumerate(lines):
        key = line.split(":", 1)[0].strip().lower() if ":" in line else None
        if key in _FIELDS:
            front.append(line)
        else:
            body_start = i
            break
    return front, "\n".join(lines[body_start:]).strip()


def _parse(raw: str, stem: str) -> dict | None:
    front, body = split_frontmatter(raw)
    d = {"name": stem, "description": "", "instructions": body or raw.strip(),
         "auto": False, "triggers": [], "file_triggers": [], "references": [],
         "disabled": False}
    for line in front:
        if ":" not in line:
            continue
        k, _, v = line.partition(":")
        k, v = k.strip().lower(), v.strip()
        if k in ("name", "description"):
            d[k] = v
        elif k in ("auto", "disabled"):
            d[k] = v.lower() in ("true", "yes", "1")
        elif k in ("triggers", "file_triggers", "references"):
            d[k] = [t.strip() for t in v.split(",") if t.strip()]
    if d["disabled"]:
        return None
    # description fallback (parity with integrations.list_skills)
    d["description"] = d["description"] or "Skill"
    return d


def list_skills(skills_dir: Path | None = None) -> list[dict]:
    d = Path(skills_dir or config.SKILLS_DIR)
    if not d.is_dir():
        return []
    imported = set(_load_imported(d))
    out = []
    for p in sorted(d.glob("*.md")):
        try:
            parsed = _parse(p.read_text(encoding="utf-8"), p.stem)
        except Exception:
            continue
        if parsed:
            parsed["imported"] = parsed["name"] in imported
            out.append(parsed)
    return out


def get_skill(name: str, skills_dir: Path | None = None) -> dict | None:
    return next((s for s in list_skills(skills_dir) if s["name"] == name), None)


def matching_skill(text: str, skills_dir: Path | None = None,
                   filenames: list[str] | None = None) -> str:
    """Name of the first auto-skill whose triggers word-match the text, or whose
    file_triggers substring-match a filename ('' if none)."""
    low = (text or "").lower()
    for s in list_skills(skills_dir):
        if not s["auto"]:
            continue
        for t in s["triggers"]:
            if re.search(r"\b" + re.escape(t.lower()) + r"\b", low):
                return s["name"]
        for ft in s["file_triggers"]:
            if any(ft.lower() in (fn or "").lower() for fn in (filenames or [])):
                return s["name"]
    return ""


# --------------------------------------------------------------------------- #
#  Importing skills (upload a .md, or sync a repository of skills)
# --------------------------------------------------------------------------- #
def _dir() -> Path:
    return Path(config.SKILLS_DIR)


def _load_imported(d: Path) -> dict:
    """name -> filename map of the skills the user imported into ``d``."""
    try:
        data = json.loads((d / _IMPORTED_MANIFEST).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save_imported(d: Path, manifest: dict) -> None:
    d.mkdir(parents=True, exist_ok=True)
    (d / _IMPORTED_MANIFEST).write_text(json.dumps(manifest, indent=2), encoding="utf-8")


def _safe_stem(name: str) -> str:
    stem = _SAFE_STEM.sub("-", (name or "skill").strip()).strip("-._")
    return (stem or "skill")[:64]


def _unique_path(d: Path, stem: str, reserved: set[str]) -> Path:
    p = d / f"{stem}.md"
    i = 1
    while p.exists() or p.name in reserved:
        p = d / f"{stem}-{i}.md"
        i += 1
    return p


def _valid_skill(content: str) -> bool:
    if not content.strip():
        return False
    if _parse(content, "x") is None:   # disabled
        return False
    # Require a real instruction body, not just a frontmatter block.
    _front, body = split_frontmatter(content)
    return bool(body.strip())


def import_skill(filename: str, content: str) -> dict:
    """Save an uploaded skill markdown file into the skills dir (path-jailed) and
    record it as user-imported so it can later be removed safely."""
    if len(content.encode("utf-8")) > _MAX_SKILL_BYTES:
        return {"ok": False, "detail": "skill file is too large"}
    if not _valid_skill(content):
        return {"ok": False, "detail": "not a valid skill (empty or disabled)"}
    d = _dir()
    d.mkdir(parents=True, exist_ok=True)
    imported = _load_imported(d)
    stem = _safe_stem(Path(filename or "skill").stem)
    path = _unique_path(d, stem, set(imported.values()))
    path.write_text(content, encoding="utf-8")
    name = _parse(content, path.stem)["name"]
    imported[name] = path.name
    _save_imported(d, imported)
    return {"ok": True, "name": name}


def remove_skill(name: str) -> dict:
    """Remove a previously-imported skill (never a bundled one)."""
    d = _dir()
    imported = _load_imported(d)
    fn = imported.get(name)
    if not fn:
        return {"ok": False, "detail": "not an imported skill"}
    root = d.resolve()
    path = (root / fn).resolve()
    if path.parent == root and path.exists():
        path.unlink()
    del imported[name]
    _save_imported(d, imported)
    return {"ok": True, "name": name}


def _discover_skill_files(root: Path) -> list[Path]:
    """Skill .md files in a synced repo: those under a skills/ dir OR carrying skill
    frontmatter. Skips dot/underscore paths, symlinks, and oversized files."""
    out: list[Path] = []
    front = re.compile(r"(?im)^\s*(name|description|triggers|auto)\s*:")
    for f in sorted(root.rglob("*.md")):
        if len(out) >= 100:
            break
        rel = f.relative_to(root)
        if any(part.startswith((".", "_")) for part in rel.parts):
            continue
        if f.is_symlink() or not f.is_file():
            continue
        try:
            if f.stat().st_size > _MAX_SKILL_BYTES:
                continue
            text = f.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        in_skills_dir = any(p.lower() in ("skill", "skills") for p in rel.parts[:-1])
        if in_skills_dir or front.search(text[:600]):
            out.append(f)
    return out


def import_skills_from_repo(url: str, ref: str = "") -> dict:
    """Clone a git repo, copy the skill files it contains into the skills dir, then
    discard the clone. Skills are plain markdown, so this is a one-shot copy (no
    persistent source to re-sync). Reuses the marketplace clone + URL validation."""
    from . import marketplace  # local import avoids a module-load cycle
    if not marketplace._valid_git_url(url):
        return {"ok": False, "detail": "not a valid git URL (use https:// or git@…)"}
    tmp = Path(tempfile.mkdtemp(prefix="ocd_skill_"))
    dest = tmp / "repo"
    try:
        try:
            marketplace._clone_repo(url, ref, dest)
        except RuntimeError as e:
            return {"ok": False, "detail": f"could not sync: {e}"}
        files = _discover_skill_files(dest)
        if not files:
            return {"ok": False, "detail": "no skills found in this repository"}
        d = _dir()
        d.mkdir(parents=True, exist_ok=True)
        imported = _load_imported(d)
        names: list[str] = []
        for f in files:
            try:
                content = f.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            if not _valid_skill(content):
                continue
            name = _parse(content, f.stem)["name"]
            path = _unique_path(d, _safe_stem(name or f.stem), set(imported.values()))
            path.write_text(content, encoding="utf-8")
            imported[name] = path.name
            names.append(name)
        if not names:
            return {"ok": False, "detail": "no valid skills found"}
        _save_imported(d, imported)
        return {"ok": True, "count": len(names), "names": names}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
