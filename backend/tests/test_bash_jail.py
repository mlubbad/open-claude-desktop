"""Phase 0 (C2): the bash tool cannot read files outside its sandbox.

The metacharacter/`..` filter did not stop absolute-path arguments, so
`cat /etc/passwd` and `cat <repo>/.env` escaped the jail. These tests pin the
argument path-jail.
"""
from ocd_core import config
from ocd_core import integrations as I


def test_absolute_path_arg_rejected():
    assert I._bash_arg_escapes_jail("/etc/passwd") is True
    assert I._bash_arg_escapes_jail("/home/user/open-claude-desktop/.env") is True


def test_home_and_windows_abs_rejected():
    assert I._bash_arg_escapes_jail("~/secrets") is True
    assert I._bash_arg_escapes_jail("C:\\Windows\\system32") is True
    assert I._bash_arg_escapes_jail("\\\\server\\share") is True


def test_flags_and_relative_args_allowed():
    assert I._bash_arg_escapes_jail("-la") is False
    assert I._bash_arg_escapes_jail("--color=auto") is False
    assert I._bash_arg_escapes_jail("notes.txt") is False
    assert I._bash_arg_escapes_jail("subdir/file.txt") is False
    assert I._bash_arg_escapes_jail("") is False


def test_run_bash_blocks_absolute_read():
    out = I.run_bash("cat /etc/passwd")
    # Task 3 (workspace-cwd-bash) made this message mode-generic ("sandbox" -> "workspace")
    # since run_bash now serves both a fixed sandbox and an arbitrary workspace root; the
    # security behavior (reject before any subprocess runs) is unchanged.
    assert "outside" in out.lower() and "rejected" in out.lower()
    assert "root:" not in out  # must not have actually read the file


def test_run_bash_still_allows_safe_relative():
    # echo of a plain literal is inside the jail and must still work.
    out = I.run_bash("echo hello")
    assert "hello" in out


def test_find_not_allowlisted():
    # C3 hardening: `find -exec/-delete` runs arbitrary non-allowlisted programs,
    # so `find` must not be in the bash allowlist at all.
    assert "find" not in I._BASH_ALLOW
    out = I.run_bash("find . -name '*.py'")
    assert "not allowlisted" in out.lower()
    # The allowlist message enumerates the permitted commands; grep/ls remain.
    assert "grep" in out and "ls" in out


def test_workspace_bash_constants_exist():
    assert config.WORKSPACE_BASH_TIMEOUT_SEC >= 30
    # runners present, read-only base preserved, dangerous fronts absent
    assert {"pytest", "npm", "python", "git"} <= I.WORKSPACE_BASH_ALLOW
    assert I._BASH_ALLOW <= I.WORKSPACE_BASH_ALLOW
    assert not ({"find", "npx", "env"} & I.WORKSPACE_BASH_ALLOW)
    assert I._INLINE_EVAL_FLAGS == {"-c", "-e", "-p", "-r", "--eval", "--print"}
    assert {"python", "node"} <= I._INTERPRETERS


def test_arg_escapes_jail_is_root_relative(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "tests").mkdir()
    # a path inside the given root is fine; absolute/parent escapes are not
    assert I._bash_arg_escapes_jail("tests", ws) is False
    assert I._bash_arg_escapes_jail("tests/unit", ws) is False
    assert I._bash_arg_escapes_jail("-k", ws) is False          # a flag
    assert I._bash_arg_escapes_jail("/etc/passwd", ws) is True  # absolute
    assert I._bash_arg_escapes_jail("../secret", ws) is True    # parent
    # default root still works (back-compat, no root passed)
    assert I._bash_arg_escapes_jail("-v") is False


# Use `python` for the execution tests — always present in the venv and portable across
# Windows/Linux (unlike `ls`/`pwd`, which aren't reliable subprocess binaries on Windows).


def test_run_bash_workspace_runs_script_in_root(tmp_path):
    # A runner (python) executes a workspace script FILE with cwd=root — proves both that
    # the runner allowlist is honored and that cwd is the workspace (script prints getcwd).
    (tmp_path / "cwd.py").write_text("import os\nprint(os.getcwd())\n")
    out = I.run_bash("python cwd.py", root=tmp_path, allow=I.WORKSPACE_BASH_ALLOW, timeout=30)
    assert tmp_path.name in out          # ran in the workspace dir
    assert "Rejected" not in out


def test_run_bash_workspace_blocks_inline_eval(tmp_path):
    out = I.run_bash('python -c "print(1)"', root=tmp_path,
                      allow=I.WORKSPACE_BASH_ALLOW, timeout=30)
    assert "inline code" in out.lower() and "rejected" in out.lower()


def test_run_bash_workspace_rejects_unlisted(tmp_path):
    out = I.run_bash("rm -rf x", root=tmp_path, allow=I.WORKSPACE_BASH_ALLOW, timeout=30)
    assert "not allowlisted" in out.lower()


def test_run_bash_workspace_rejects_outside_arg(tmp_path):
    # cat is in the read-only base (allowed); the arg-jail rejects the absolute path
    # BEFORE any subprocess runs, so this is portable (no dependency on `cat` existing).
    out = I.run_bash("cat /etc/passwd", root=tmp_path, allow=I.WORKSPACE_BASH_ALLOW, timeout=30)
    assert "outside" in out.lower() and "rejected" in out.lower()


def test_run_bash_nonworkspace_unchanged():
    # no root/allow -> read-only base + SANDBOX_ROOT (regression): a runner is NOT allowed
    out = I.run_bash("pytest")
    assert "not allowlisted" in out.lower()


def test_run_bash_workspace_rejects_bare_interpreter(tmp_path):
    out = I.run_bash("python", root=tmp_path, allow=I.WORKSPACE_BASH_ALLOW, timeout=5)
    assert "interpreter must run a workspace file" in out.lower() or "rejected" in out.lower()
    assert "inline code" in out.lower() or "repl" in out.lower() or "workspace file" in out.lower()


def test_run_bash_workspace_blocks_interpreter_front(tmp_path):
    # uv/poetry fronting an interpreter with inline eval must be rejected by the GUARD,
    # before any subprocess runs (independent of whether uv/poetry is installed).
    for cmd in ("uv run python -c \"print(1)\"", "poetry run python -c \"print(1)\""):
        out = I.run_bash(cmd, root=tmp_path, allow=I.WORKSPACE_BASH_ALLOW, timeout=5)
        assert "workspace file" in out.lower() and "rejected" in out.lower(), cmd


def test_run_bash_workspace_allows_runner_via_uv(tmp_path):
    # `uv run pytest` has no interpreter+eval pattern -> the guard must NOT fire
    # (it may still fail for lack of a project, but not with the guard message).
    out = I.run_bash("uv run pytest --version", root=tmp_path, allow=I.WORKSPACE_BASH_ALLOW, timeout=10)
    assert "must run a workspace file" not in out.lower()


def test_run_bash_workspace_missing_root_errors(tmp_path):
    ghost = tmp_path / "does" / "not" / "exist"
    out = I.run_bash("python x.py", root=ghost, allow=I.WORKSPACE_BASH_ALLOW, timeout=5)
    assert "not a directory" in out.lower()
    assert not ghost.exists()   # not fabricated


def test_run_bash_blocks_attached_inline_eval(tmp_path):
    for cmd in ('python -cprint(1)', 'python3 -cprint(1)', 'node --eval=1', 'node -p1'):
        out = I.run_bash(cmd, root=tmp_path, allow=I.WORKSPACE_BASH_ALLOW, timeout=5)
        assert "workspace file" in out.lower() and "rejected" in out.lower(), cmd


def test_run_bash_blocks_eval_after_value_option(tmp_path):
    out = I.run_bash('python -W ignore -c "print(1)"', root=tmp_path,
                     allow=I.WORKSPACE_BASH_ALLOW, timeout=5)
    assert "workspace file" in out.lower()


def test_run_bash_allows_module_tool_with_own_c_flag(tmp_path):
    # `python -m pytest -c cfg` must NOT be misread as python's -c eval (pytest's -c).
    out = I.run_bash("python -m pytest -c pytest.ini --version", root=tmp_path,
                     allow=I.WORKSPACE_BASH_ALLOW, timeout=15)
    assert "must run a workspace file" not in out.lower()   # not blocked by the eval guard


def test_arg_jail_blocks_flag_value_path(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    assert I._bash_arg_escapes_jail("--git-dir=/etc/passwd", ws) is True
    assert I._bash_arg_escapes_jail("--work-tree=C:/Windows", ws) is True
    assert I._bash_arg_escapes_jail("--config=subdir/x", ws) is False   # inside root, fine


def test_run_bash_git_dir_escape_blocked(tmp_path):
    out = I.run_bash("git --git-dir=/etc/passwd log", root=tmp_path,
                     allow=I.WORKSPACE_BASH_ALLOW, timeout=5)
    assert "outside" in out.lower() and "rejected" in out.lower()


def test_run_bash_workspace_strips_secret_env(tmp_path, monkeypatch):
    monkeypatch.setenv("OCD_API_TOKEN", "TOKLEAK-abc")
    monkeypatch.setenv("MY_PROVIDER_KEY", "KEYLEAK-abc")
    (tmp_path / "dump.py").write_text(
        "import os\nprint('TOK=' + os.environ.get('OCD_API_TOKEN', ''))\n"
        "print('KEY=' + os.environ.get('MY_PROVIDER_KEY', ''))\n")
    out = I.run_bash("python dump.py", root=tmp_path, allow=I.WORKSPACE_BASH_ALLOW, timeout=10)
    assert "TOKLEAK-abc" not in out and "KEYLEAK-abc" not in out
    assert "TOK=" in out   # the script DID run (var just empty)


def test_run_bash_blocks_value_fronted_eval(tmp_path):
    # eval flag hidden behind a value-taking option must still be caught
    for cmd in ('node --require ./foo.js -e "console.log(1)"',
                'node -r ./foo.js -e "console.log(1)"',
                'python --check-hash-based-pycs default -c "print(1)"'):
        out = I.run_bash(cmd, root=tmp_path, allow=I.WORKSPACE_BASH_ALLOW, timeout=5)
        assert "workspace file" in out.lower() and "rejected" in out.lower(), cmd


def test_run_bash_allows_module_downstream_flags(tmp_path):
    # after -m, the module's own -c/-p are NOT the interpreter's eval flag
    out = I.run_bash("python -m pytest -c pytest.ini -p no:cacheprovider --version",
                     root=tmp_path, allow=I.WORKSPACE_BASH_ALLOW, timeout=15)
    assert "must run a workspace file" not in out.lower()
