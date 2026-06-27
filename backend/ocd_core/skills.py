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
import re
from pathlib import Path

from . import config

_FIELDS = {"name", "description", "auto", "triggers", "file_triggers",
           "disabled", "references"}


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
    out = []
    for p in sorted(d.glob("*.md")):
        try:
            parsed = _parse(p.read_text(encoding="utf-8"), p.stem)
        except Exception:
            continue
        if parsed:
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
