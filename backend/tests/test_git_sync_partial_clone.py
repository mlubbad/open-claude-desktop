"""Text-only partial clone + honest size accounting.

Seen in the field: adding real marketplaces failed with ``400: repository is too
large`` — a 218 MB prompt-collection repo whose *scannable text* was 9 MB. Two root
causes, both pinned here:

  * the clone fetched EVERYTHING (images, datasets, site assets) although discovery
    only reads small text files -> clone_repo now does a ``--filter=blob:limit=512k
    --no-checkout`` partial clone plus per-pattern text checkouts, with a plain
    shallow clone as the fallback for servers/gits without partial-clone support;
  * ``dir_size`` counted ``.git`` packfile metadata, silently halving the budget.
"""
import subprocess
from pathlib import Path

from ocd_core import config, git_sync, marketplace


class _Recorder:
    """Stands in for subprocess.run, capturing every git invocation."""

    def __init__(self, fail_on=None):
        self.calls: list[list[str]] = []
        self.fail_on = fail_on or (lambda cmd: False)

    def __call__(self, cmd, **kw):
        self.calls.append(list(cmd))
        if self.fail_on(cmd):
            raise subprocess.CalledProcessError(128, cmd, stderr=b"fatal: nope")
        return subprocess.CompletedProcess(cmd, 0)


def test_clone_is_partial_and_checks_out_only_text(monkeypatch, tmp_path):
    rec = _Recorder()
    monkeypatch.setattr(git_sync.subprocess, "run", rec)
    git_sync.clone_repo("https://github.com/o/r", "", tmp_path / "dest")

    clone = rec.calls[0]
    assert "--filter=blob:limit=512k" in clone
    assert "--no-checkout" in clone
    assert "--depth" in clone
    # One checkout per text pattern, nothing else materialized.
    checkouts = [c for c in rec.calls[1:] if c[:2] == ["git", "-C"]]
    patterns = [c[-1] for c in checkouts]
    assert patterns == list(git_sync.TEXT_PATTERNS)
    assert "*.py" in patterns and "*.md" in patterns and "*.json" in patterns


def test_pattern_without_matches_is_tolerated(monkeypatch, tmp_path):
    """git exits non-zero when a pathspec matches nothing — a repo with no *.py must
    still get its *.md (and the clone must still succeed)."""
    rec = _Recorder(fail_on=lambda cmd: cmd[-1] == "*.py")
    monkeypatch.setattr(git_sync.subprocess, "run", rec)
    git_sync.clone_repo("https://github.com/o/r", "", tmp_path / "dest")
    assert [c[-1] for c in rec.calls if c[:2] == ["git", "-C"]] == list(git_sync.TEXT_PATTERNS)


def test_partial_clone_failure_falls_back_to_plain_clone(monkeypatch, tmp_path):
    """Old git / server without partial clone: retry as a plain shallow clone."""
    rec = _Recorder(fail_on=lambda cmd: "--filter=blob:limit=512k" in cmd)
    monkeypatch.setattr(git_sync.subprocess, "run", rec)
    git_sync.clone_repo("https://github.com/o/r", "", tmp_path / "dest")
    plain = rec.calls[-1]
    assert plain[:2] == ["git", "clone"]
    assert "--filter=blob:limit=512k" not in plain and "--no-checkout" not in plain


def test_dir_size_ignores_git_metadata(tmp_path):
    (tmp_path / "plugin.py").write_bytes(b"x" * 1000)
    (tmp_path / ".git" / "objects").mkdir(parents=True)
    (tmp_path / ".git" / "objects" / "pack").write_bytes(b"y" * 10_000_000)
    assert git_sync.dir_size(tmp_path) == 1000


def test_too_large_error_reports_size_cap_and_remedy(monkeypatch, tmp_path):
    def _fake_clone(url, ref, dest: Path):
        dest.mkdir(parents=True)
        (dest / "big.md").write_bytes(b"z" * (2 * 1024 * 1024))

    monkeypatch.setattr(marketplace.git_sync, "clone_repo", _fake_clone)
    monkeypatch.setattr(marketplace, "_sources_dir", lambda: tmp_path / "sources")
    monkeypatch.setattr(marketplace, "_sources_file", lambda: tmp_path / "sources.json")
    monkeypatch.setattr(config, "MARKETPLACE_MAX_SOURCE_BYTES", 1024 * 1024)  # 1 MB cap

    res = marketplace.add_source("https://github.com/o/r")
    assert res["ok"] is False
    assert "2 MB" in res["detail"] and "1 MB" in res["detail"]
    assert "MARKETPLACE_MAX_SOURCE_MB" in res["detail"]
