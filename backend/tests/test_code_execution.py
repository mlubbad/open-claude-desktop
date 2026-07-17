"""code_execution parity: the agent must really RUN Python (not fabricate it), stream
its output, and surface the files it produces so a request like "run this and give me the
CSV" yields a real, downloadable file — the reported hallucination bug."""
import sys

import pytest
from ocd_core import config, integrations


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    monkeypatch.setattr(integrations, "SANDBOX_ROOT", tmp_path / "_sandbox")
    # Explicitly opt into the host capability under test, then force local mode: CI
    # may have a docker binary on PATH but no running daemon.
    monkeypatch.setattr(config, "HOST_EXECUTION_ENABLED", True)
    monkeypatch.setattr(integrations, "_code_execution_mode", lambda: "local")
    return tmp_path


def test_local_run_streams_output_and_produces_files(sandbox):
    streamed: list[tuple[str, str]] = []
    code = (
        "import csv\n"
        "print('processing')\n"
        "with open('merged.csv','w',newline='') as f:\n"
        "    csv.writer(f).writerows([['Country','Clicks'],['US','134'],['Egypt','111']])\n"
        "print('wrote merged.csv')\n"
    )
    res = integrations.execute_code(code, "general", lambda s, t: streamed.append((s, t)))

    assert res["ok"] is True
    assert res["return_code"] == 0
    assert res["engine"] == "local"
    # Output really streamed (not captured-only).
    joined = "".join(t for _, t in streamed)
    assert "processing" in joined and "wrote merged.csv" in joined
    # The produced CSV is detected, classified, and its text inlined for the artifact.
    csv_file = next(f for f in res["files"] if f["path"] == "merged.csv")
    assert csv_file["kind"] == "csv"
    assert "Country,Clicks" in csv_file["text"]
    assert "Egypt,111" in csv_file["text"]


def test_files_diff_only_reports_new_or_changed(sandbox):
    integrations.execute_code("open('a.txt','w').write('one')", "p1")
    # A second run that writes a different file must not re-report the untouched a.txt.
    res = integrations.execute_code("open('b.txt','w').write('two')", "p1")
    paths = {f["path"] for f in res["files"]}
    assert "b.txt" in paths
    assert "a.txt" not in paths


def test_exec_scratch_dir_is_not_reported_as_a_produced_file(sandbox):
    res = integrations.execute_code("print('hi')", "general")
    assert all(".exec" not in f["path"] for f in res["files"])


def test_nonzero_exit_is_not_ok_and_captures_stderr(sandbox):
    res = integrations.execute_code("import sys; sys.exit(3)", "general")
    assert res["ok"] is False
    assert res["return_code"] == 3


def test_runtime_error_surfaces_traceback(sandbox):
    res = integrations.execute_code("raise ValueError('boom')", "general")
    assert res["ok"] is False
    assert "ValueError" in res["stderr"] and "boom" in res["stderr"]


def test_off_mode_refuses_without_running(monkeypatch, tmp_path):
    monkeypatch.setattr(integrations, "SANDBOX_ROOT", tmp_path / "_sandbox")
    monkeypatch.setattr(integrations, "_code_execution_mode", lambda: "off")
    res = integrations.execute_code("open('should_not_exist.txt','w').write('x')", "general")
    assert res["ok"] is False
    assert res["engine"] == "off"
    assert res["files"] == []
    # Nothing ran → no workspace file created.
    assert not (tmp_path / "_sandbox" / "general" / "should_not_exist.txt").exists()


def test_docker_mode_without_docker_is_a_clean_error(monkeypatch, tmp_path):
    monkeypatch.setattr(integrations, "SANDBOX_ROOT", tmp_path / "_sandbox")
    monkeypatch.setattr(integrations, "_code_execution_mode", lambda: "docker")
    monkeypatch.setattr(integrations.shutil, "which", lambda _n: None)
    res = integrations.execute_code("print(1)", "general")
    assert res["ok"] is False
    assert res["engine"] == "docker-missing"
    assert "Docker" in res["stderr"]


def test_scrubbed_env_drops_secrets(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-secret")
    monkeypatch.setenv("GROQ_API_KEY", "gsk-secret")
    env = integrations._scrubbed_env(tmp_path)
    assert "OPENAI_API_KEY" not in env
    assert "GROQ_API_KEY" not in env
    assert env.get("HOME") == str(tmp_path)


def test_output_is_capped(sandbox, monkeypatch):
    monkeypatch.setattr(integrations, "_EXEC_OUTPUT_CAP", 500)
    res = integrations.execute_code("print('x' * 100000)", "general")
    # Capped well below what the script printed, and flagged as truncated.
    assert len(res["stdout"]) <= 2000
    assert "truncated" in res["stderr"]


def test_timeout_is_enforced(sandbox, monkeypatch):
    monkeypatch.setattr(integrations, "_EXEC_TIMEOUT_SEC", 2)
    res = integrations.execute_code("import time\nwhile True:\n    time.sleep(0.2)", "general")
    assert res["timed_out"] is True
    assert res["ok"] is False


def test_format_execution_result_is_truthful(sandbox):
    res = integrations.execute_code("print('hello')\nopen('x.txt','w').write('hi')", "general")
    text = integrations.format_execution_result(res)
    assert "return_code: 0" in text
    assert "hello" in text
    assert "x.txt" in text  # the model is told which files were produced


def test_run_python_backcompat_wrapper(sandbox):
    out = integrations.run_python("print('legacy')")
    assert "return_code: 0" in out
    assert "legacy" in out


def test_code_execution_mode_default_is_valid_and_falls_back(monkeypatch):
    from ocd_core import settings as settings_mod
    assert config.DEFAULT_SETTINGS["code_execution"] in config.CODE_EXECUTION_MODES
    # An unknown persisted value falls back to fail-closed Docker mode.
    monkeypatch.setattr(settings_mod, "get_settings", lambda: {"code_execution": "bogus"})
    assert integrations._code_execution_mode() == "docker"


def test_safe_project_blocks_traversal():
    # A crafted project id can't escape the sandbox root (download/tree/file route jail).
    assert integrations.safe_project("../../etc") == "etc"
    assert integrations.safe_project("../../../") == "general"
    assert integrations.safe_project("my_project-2") == "my_project-2"
    assert integrations.safe_project("") == "general"


def test_symlinked_host_file_is_not_surfaced(sandbox, tmp_path):
    # A sandboxed script that symlinks a host file must NOT have that file read/surfaced.
    secret = tmp_path / "secret.txt"
    secret.write_text("TOP SECRET")
    res = integrations.execute_code(
        f"import os; os.symlink({str(secret)!r}, 'leak.txt')", "general")
    # The symlink is skipped by the produced-file diff — no host content leaks out.
    leaked = [f for f in res["files"] if f["path"] == "leak.txt"]
    assert leaked == [] or "TOP SECRET" not in (leaked[0].get("text") or "")


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX resource limits")
def test_posix_limits_callable():
    # Smoke: the preexec limiter is importable/callable shape (real effect is in-child).
    assert callable(integrations._posix_limits)
