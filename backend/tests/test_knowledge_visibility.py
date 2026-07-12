"""Uploaded project files must be VISIBLE to the agent and REACHABLE by code
execution — the fix for the "I couldn't find the CSV you uploaded" failure, where
the model (blind to the upload) hunted the disk through filesystem MCP tools,
hallucinated a folder, and asked the user for the path.

Two halves: the system prompt lists the project's knowledge files (with explicit
don't-guess-paths guidance), and the exec workspace carries a knowledge/ mirror of
the raw files so "modify this CSV" can operate on the actual bytes."""
import os

from ocd_core import agent, config, integrations


def _seed(tmp_path, pid="proj1", name="sales.csv", text="a,b\n1,2\n"):
    kb = tmp_path / pid / "knowledge"
    kb.mkdir(parents=True, exist_ok=True)
    (kb / name).write_text(text)
    return kb / name


def test_prompt_section_lists_uploads_and_forbids_path_guessing(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "PROJECTS_DIR", tmp_path)
    _seed(tmp_path)
    sec = agent._knowledge_files_section("proj1", code_exec=True)
    assert "sales.csv" in sec
    assert "search_project_knowledge" in sec
    assert "knowledge/" in sec  # points code execution at the workspace mirror
    assert "never" in sec and "guess disk paths" in sec


def test_prompt_section_omits_exec_mirror_when_exec_is_off(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "PROJECTS_DIR", tmp_path)
    _seed(tmp_path)
    sec = agent._knowledge_files_section("proj1", code_exec=False)
    assert "sales.csv" in sec
    assert "pd.read_csv" not in sec


def test_prompt_section_absent_without_files_or_project(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "PROJECTS_DIR", tmp_path)
    assert agent._knowledge_files_section("empty_project", code_exec=True) is None
    assert agent._knowledge_files_section(None, code_exec=True) is None


def test_exec_workdir_mirrors_knowledge_files(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "PROJECTS_DIR", tmp_path / "projects")
    monkeypatch.setattr(integrations, "SANDBOX_ROOT", tmp_path / "sandbox")
    src = _seed(tmp_path / "projects", "p1", "data.csv", "a,b\n1,2\n")

    root = integrations._exec_workdir("p1")
    mirror = root / "knowledge" / "data.csv"
    assert mirror.read_text() == "a,b\n1,2\n"

    # A re-upload (newer content) refreshes the mirror on the next execution…
    src.write_text("a,b\n9,9\n")
    os.utime(src, (src.stat().st_mtime + 10, src.stat().st_mtime + 10))
    integrations._exec_workdir("p1")
    assert mirror.read_text() == "a,b\n9,9\n"

    # …and the mirror never appears in produced-files: it exists BEFORE the snapshot.
    before = integrations._snapshot(root)
    assert integrations._produced_files(before, root) == []


def test_exec_workdir_survives_missing_knowledge_dir(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "PROJECTS_DIR", tmp_path / "projects")
    monkeypatch.setattr(integrations, "SANDBOX_ROOT", tmp_path / "sandbox")
    root = integrations._exec_workdir("no_uploads")  # no knowledge dir at all
    assert root.is_dir()
    assert not (root / "knowledge").exists()


def test_execute_code_transforms_an_uploaded_csv_end_to_end(monkeypatch, tmp_path):
    """The user scenario itself: upload a CSV to the project, then run code that
    modifies it — the code reads the mirror, and the result surfaces as a real
    produced file (not the pristine mirror)."""
    monkeypatch.setattr(config, "PROJECTS_DIR", tmp_path / "projects")
    monkeypatch.setattr(integrations, "SANDBOX_ROOT", tmp_path / "sandbox")
    monkeypatch.setattr(integrations, "_code_execution_mode", lambda: "local")
    _seed(tmp_path / "projects", "p1", "data.csv", "name,qty\nwidget,2\n")

    code = (
        "with open('knowledge/data.csv') as f:\n"
        "    rows = f.read().splitlines()\n"
        "rows.append('gadget,5')\n"
        "with open('data_updated.csv', 'w') as f:\n"
        "    f.write('\\n'.join(rows) + '\\n')\n"
        "print('rows:', len(rows))\n"
    )
    res = integrations.execute_code(code, "p1")
    assert res["ok"] is True, res["stderr"]
    produced = {f["path"] for f in res["files"]}
    assert "data_updated.csv" in produced
    assert not any(p.startswith("knowledge/") for p in produced)


def test_mirror_edits_do_not_touch_the_original(monkeypatch, tmp_path):
    """Code may scribble on its knowledge/ copies; the uploaded original is pristine."""
    monkeypatch.setattr(config, "PROJECTS_DIR", tmp_path / "projects")
    monkeypatch.setattr(integrations, "SANDBOX_ROOT", tmp_path / "sandbox")
    src = _seed(tmp_path / "projects", "p1", "data.csv", "a,b\n1,2\n")
    root = integrations._exec_workdir("p1")
    (root / "knowledge" / "data.csv").write_text("MUTATED")
    assert src.read_text() == "a,b\n1,2\n"
