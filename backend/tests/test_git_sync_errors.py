"""clone_error_detail — actionable git failure messages.

Seen in the field: adding a marketplace surfaced ``400: could not sync: and the
repository exists.`` — the LAST line of git's multi-line SSH failure, with the actual
reason discarded. These tests pin the distillation (keep the real message) and the
what-to-do hints for the failure shapes users actually hit.
"""
import subprocess
from pathlib import Path

import pytest
from ocd_core import git_sync
from ocd_core.git_sync import clone_error_detail

_SSH_FAILURE = b"""Cloning into 'claude-video'...
fatal: Could not read from remote repository.

Please make sure you have the correct access rights
and the repository exists.
"""


def test_ssh_failure_keeps_reason_and_hints_at_insteadof():
    msg = clone_error_detail(_SSH_FAILURE)
    # The real reason survives (not just the dangling last line)…
    assert "Could not read from remote repository" in msg
    # …and the user is told what is actually going on and what to try.
    assert "insteadOf" in msg
    assert "git clone <url>" in msg


def test_credentials_failure_hints_private_repo():
    msg = clone_error_detail(
        b"Cloning into 'x'...\nfatal: could not read Username for "
        b"'https://github.com': terminal prompts disabled")
    assert "private" in msg.lower()


def test_missing_branch_hints_default_branch():
    msg = clone_error_detail(
        b"Cloning into 'x'...\nwarning: Could not find remote branch dev to clone.\n"
        b"fatal: Remote branch dev not found in upstream origin")
    assert "leave the branch field empty" in msg


def test_network_failure_hints_connectivity():
    msg = clone_error_detail(
        b"Cloning into 'x'...\nfatal: unable to access 'https://github.com/o/r/': "
        b"Could not resolve host: github.com")
    assert "network" in msg.lower()


def test_empty_stderr_still_says_something():
    assert clone_error_detail(b"") == "git clone failed"
    assert clone_error_detail(None) == "git clone failed"


def test_clone_repo_raises_the_distilled_message(monkeypatch, tmp_path):
    def _boom(cmd, **kw):
        raise subprocess.CalledProcessError(128, cmd, stderr=_SSH_FAILURE)
    monkeypatch.setattr(git_sync.subprocess, "run", _boom)
    with pytest.raises(RuntimeError) as ei:
        git_sync.clone_repo("https://github.com/o/r", "", tmp_path / "dest")
    assert "Could not read from remote repository" in str(ei.value)
    # Never the old dangling fragment as the whole story.
    assert str(ei.value) != "and the repository exists."


def test_foreign_repo_hint_detects_agent_skills_repo(tmp_path):
    """A Claude Code plugin / Agent Skills repo (SKILL.md + .claude-plugin/) synced as
    a plugin marketplace gets pointed at the Skills importer, not a dead end."""
    from ocd_core import marketplace
    (tmp_path / "skills" / "watch").mkdir(parents=True)
    (tmp_path / "skills" / "watch" / "SKILL.md").write_text("---\nname: watch\n---\nhi")
    (tmp_path / ".claude-plugin").mkdir()
    (tmp_path / ".claude-plugin" / "plugin.json").write_text("{}")
    hint = marketplace._foreign_repo_hint(tmp_path)
    assert "Skills" in hint and "Add from repository" in hint


def test_foreign_repo_hint_empty_for_ordinary_repo(tmp_path):
    from ocd_core import marketplace
    (tmp_path / "README.md").write_text("just a repo")
    assert marketplace._foreign_repo_hint(tmp_path) == ""


def test_add_source_surfaces_the_skills_redirect(monkeypatch, tmp_path):
    """End-to-end through add_source: clone succeeds, repo is Claude-Code-shaped,
    the 400 detail tells the user where to import it."""
    from ocd_core import marketplace

    def _fake_clone(url, ref, dest: Path):
        (dest / "skills" / "watch").mkdir(parents=True)
        (dest / "skills" / "watch" / "SKILL.md").write_text("---\nname: watch\n---\nhi")

    monkeypatch.setattr(marketplace.git_sync, "clone_repo", _fake_clone)
    monkeypatch.setattr(marketplace, "_sources_dir", lambda: tmp_path / "sources")
    monkeypatch.setattr(marketplace, "_sources_file", lambda: tmp_path / "sources.json")
    res = marketplace.add_source("https://github.com/bradautomates/claude-video")
    assert res["ok"] is False
    assert "Skills" in res["detail"]
