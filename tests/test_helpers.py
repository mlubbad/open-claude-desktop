"""Unit tests for pure helpers in app.py (#15 — broaden coverage).

Loads app.py by file path (same pattern as the other suites) and exercises the
small, deterministic helpers that had no coverage.
"""
import importlib.util
import os

_HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load_app():
    spec = importlib.util.spec_from_file_location(
        "aj360app_helpers", os.path.join(_HERE, "app.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


app = _load_app()


def test_fmt_bytes():
    assert app._fmt_bytes(0) == "0 B"
    assert app._fmt_bytes(512) == "512.0 B"
    assert app._fmt_bytes(1024) == "1.0 KB"
    assert app._fmt_bytes(1536) == "1.5 KB"
    assert app._fmt_bytes(1024 ** 3) == "1.0 GB"


def test_slugify():
    assert app._slugify("Hello World!") == "hello-world"
    assert app._slugify("  Multiple   Spaces  ") == "multiple-spaces"
    assert app._slugify("") == "untitled"
    assert app._slugify("!!!") == "untitled"


def test_check_banned_aliases():
    # A normal alias is fine.
    assert app._check_banned_aliases("SELECT 1 AS foo") is None
    # A reserved word used as an alias is rejected, and is named in the message.
    err = app._check_banned_aliases("SELECT 1 AS rows")
    assert err and "rows" in err


if __name__ == "__main__":
    funcs = [v for k, v in sorted(globals().items())
             if k.startswith("test_") and callable(v)]
    failures = []
    for f in funcs:
        try:
            f()
            print("PASS", f.__name__)
        except AssertionError as e:
            print("FAIL", f.__name__, e)
            failures.append(f.__name__)
    print("RESULT:", "ALL PASS" if not failures else f"{len(failures)} FAILED: {failures}")
    raise SystemExit(1 if failures else 0)
