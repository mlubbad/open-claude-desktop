"""Phase 0 (C2): the bash tool cannot read files outside its sandbox.

The metacharacter/`..` filter did not stop absolute-path arguments, so
`cat /etc/passwd` and `cat <repo>/.env` escaped the jail. These tests pin the
argument path-jail.
"""
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
    assert "outside the sandbox" in out
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
