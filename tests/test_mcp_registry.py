"""Integration tests for the single-spawn MCP registry (mcp_registry.py).

These spawn the bundled demo MCP server (mcp_servers/demo_server.py) for real
and verify that the registry keeps ONE persistent session across calls (no
re-spawn), returns correct results, and stays usable after an error.

Run:  venv312\\Scripts\\python.exe tests/test_mcp_registry.py
or:   venv312\\Scripts\\python.exe -m pytest tests/test_mcp_registry.py
"""
import importlib.util
import os
import sys

_HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DEMO = os.path.join(_HERE, "mcp_servers", "demo_server.py")


def _load_registry_module():
    spec = importlib.util.spec_from_file_location(
        "ocd_mcp_registry",
        os.path.join(_HERE, "aj360_app", "aj360_app", "mcp_registry.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_mod = _load_registry_module()


def _cfg():
    return {"id": "demo_test", "command": sys.executable, "args": [_DEMO]}


def _new_registry():
    return _mod.MCPRegistry()


def test_discover_lists_demo_tools():
    r = _new_registry()
    try:
        names = {t["name"] for t in r.discover(_cfg(), timeout=30)}
        assert {"echo", "server_time", "word_count", "reverse"} <= names
    finally:
        r.shutdown()


def test_calls_return_correct_results():
    r = _new_registry()
    try:
        assert "hello" in r.call(_cfg(), "echo", {"text": "hello"}, timeout=30)
        assert "cba" in r.call(_cfg(), "reverse", {"text": "abc"}, timeout=30)
        assert "3" in r.call(_cfg(), "word_count", {"text": "a b c"}, timeout=30)
    finally:
        r.shutdown()


def test_single_session_reused_across_calls():
    r = _new_registry()
    try:
        r.discover(_cfg(), timeout=30)
        key = _mod._server_key(_cfg())
        sess1 = r._sessions.get(key)
        r.call(_cfg(), "echo", {"text": "one"}, timeout=30)
        r.call(_cfg(), "echo", {"text": "two"}, timeout=30)
        sess2 = r._sessions.get(key)
        # Exactly one live session, and it is the SAME object => no re-spawn.
        assert len(r._sessions) == 1
        assert sess1 is not None and sess1 is sess2
    finally:
        r.shutdown()


def test_error_does_not_hang_and_registry_recovers():
    r = _new_registry()
    try:
        # A bad tool name must not hang; it either returns an error string or
        # raises — either way it completes quickly.
        try:
            r.call(_cfg(), "no_such_tool", {}, timeout=15)
        except Exception:
            pass
        # Registry is still usable afterwards.
        assert "ok" in r.call(_cfg(), "echo", {"text": "ok"}, timeout=30)
    finally:
        r.shutdown()


if __name__ == "__main__":
    funcs = [v for k, v in sorted(globals().items())
             if k.startswith("test_") and callable(v)]
    failures = []
    for f in funcs:
        try:
            f()
            print("PASS", f.__name__)
        except Exception as e:
            print("FAIL", f.__name__, "->", repr(e)[:200])
            failures.append(f.__name__)
    print("RESULT:", "ALL PASS" if not failures else f"{len(failures)} FAILED: {failures}")
    raise SystemExit(1 if failures else 0)
