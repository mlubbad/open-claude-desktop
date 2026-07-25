# backend/tests/test_harness_hooks.py
import asyncio
import sys

from ocd_core import config
from ocd_core.harness import hooks


def test_config_defaults():
    assert config.DEFAULT_SETTINGS["hooks"] == {}
    assert config.HOOK_TIMEOUT_SEC == 30
    assert config.HOOK_TIMEOUT_MAX_SEC == 120


def test_events_are_the_five_v1_events():
    assert hooks.EVENTS == ("SessionStart", "UserPromptSubmit", "PreToolUse",
                            "PostToolUse", "Stop")


def test_load_hooks_empty_when_unconfigured(monkeypatch):
    monkeypatch.setattr(hooks.settings, "get_settings", lambda: {})
    assert hooks.load_hooks("PreToolUse") == []


def test_load_hooks_returns_configured_list(monkeypatch):
    cfg = {"hooks": {"PreToolUse": [{"matcher": "bash", "command": "python x.py"}]}}
    monkeypatch.setattr(hooks.settings, "get_settings", lambda: cfg)
    got = hooks.load_hooks("PreToolUse")
    assert len(got) == 1 and got[0]["command"] == "python x.py"


def test_load_hooks_ignores_unknown_event_and_bad_shapes(monkeypatch):
    cfg = {"hooks": {"NotAnEvent": [{"command": "x"}],
                     "PreToolUse": ["not-a-dict", {"no_command": 1}]}}
    monkeypatch.setattr(hooks.settings, "get_settings", lambda: cfg)
    assert hooks.load_hooks("NotAnEvent") == []      # unknown event
    assert hooks.load_hooks("PreToolUse") == []      # both entries invalid -> dropped


# add to backend/tests/test_harness_hooks.py
def test_matches_star_and_missing_matcher():
    assert hooks.matches({"matcher": "*", "command": "x"}, "bash") is True
    assert hooks.matches({"command": "x"}, "bash") is True          # omitted = all
    assert hooks.matches({"matcher": "", "command": "x"}, "bash") is True


def test_matches_regex_alternation():
    h = {"matcher": "bash|edit_file", "command": "x"}
    assert hooks.matches(h, "bash") is True
    assert hooks.matches(h, "edit_file") is True
    assert hooks.matches(h, "read_file") is False


def test_matches_is_anchored_not_substring():
    # "edit" must NOT match "edit_file" — a matcher names a tool, not a prefix.
    assert hooks.matches({"matcher": "edit", "command": "x"}, "edit_file") is False


def test_matches_bad_regex_is_false_not_raise():
    assert hooks.matches({"matcher": "[unclosed", "command": "x"}, "bash") is False


def test_matches_true_when_no_tool_name():
    # non-tool events (SessionStart/Stop/UserPromptSubmit) ignore the matcher
    assert hooks.matches({"matcher": "bash", "command": "x"}, None) is True


# add to backend/tests/test_harness_hooks.py
def test_parse_json_decision():
    d = hooks.parse_output(0, '{"permissionDecision":"deny","reason":"nope"}', "", "PreToolUse")
    assert d.decision == "deny" and d.reason == "nope"


def test_parse_json_context_only():
    d = hooks.parse_output(0, '{"additionalContext":"remember X"}', "", "SessionStart")
    assert d.decision is None and d.context == "remember X"


def test_parse_exit_zero_non_json_is_no_opinion():
    d = hooks.parse_output(0, "just some log text", "", "PreToolUse")
    assert d.decision is None and d.context == ""


def test_parse_exit_two_is_deny_with_stderr_reason():
    d = hooks.parse_output(2, "", "policy says no", "PreToolUse")
    assert d.decision == "deny" and "policy says no" in d.reason


def test_parse_other_nonzero_denies_for_blocking_event():
    d = hooks.parse_output(1, "", "boom", "PreToolUse")
    assert d.decision == "deny"          # fail CLOSED


def test_parse_other_nonzero_is_no_opinion_for_observational_event():
    d = hooks.parse_output(1, "", "boom", "PostToolUse")
    assert d.decision is None            # fail OPEN


def test_parse_malformed_json_denies_for_blocking_event():
    d = hooks.parse_output(0, '{"permissionDecision": ', "", "PreToolUse")
    assert d.decision == "deny"


def test_parse_malformed_json_is_no_opinion_for_observational_event():
    assert hooks.parse_output(0, '{"nope": ', "", "Stop").decision is None


def test_parse_unknown_decision_value_denies_for_blocking_event():
    d = hooks.parse_output(0, '{"permissionDecision":"banana"}', "", "PreToolUse")
    assert d.decision == "deny"


def test_merge_strictest_wins():
    a = hooks.HookDecision(decision="allow")
    b = hooks.HookDecision(decision="ask")
    c = hooks.HookDecision(decision="deny", reason="r")
    assert hooks.merge([a, b]).decision == "ask"
    assert hooks.merge([a, b, c]).decision == "deny"
    assert hooks.merge([a]).decision == "allow"
    assert hooks.merge([]).decision is None


def test_merge_concatenates_context():
    out = hooks.merge([hooks.HookDecision(context="one"), hooks.HookDecision(context="two")])
    assert "one" in out.context and "two" in out.context


def _hook_settings(monkeypatch, event, command, matcher="*", timeout=None):
    entry = {"matcher": matcher, "command": command}
    if timeout is not None:
        entry["timeout"] = timeout
    monkeypatch.setattr(hooks.settings, "get_settings", lambda: {"hooks": {event: [entry]}})


def _write(tmp_path, name, body):
    p = tmp_path / name
    p.write_text(body, encoding="utf-8")
    return p


def test_run_no_hooks_configured_spawns_nothing(monkeypatch):
    monkeypatch.setattr(hooks.settings, "get_settings", lambda: {})
    called = []
    monkeypatch.setattr(hooks.asyncio, "create_subprocess_exec",
                        lambda *a, **k: called.append(a))
    d = asyncio.run(hooks.run("PreToolUse", {"tool_name": "bash"}))
    assert d.decision is None and called == []


def test_run_reads_payload_on_stdin_and_denies(monkeypatch, tmp_path):
    # the hook echoes a deny only if it actually received the tool name on stdin
    s = _write(tmp_path, "deny.py",
               "import json,sys\n"
               "p=json.load(sys.stdin)\n"
               "print(json.dumps({'permissionDecision':'deny','reason':'saw '+p['tool_name']}))\n")
    _hook_settings(monkeypatch, "PreToolUse", f'"{sys.executable}" "{s}"')
    d = asyncio.run(hooks.run("PreToolUse", {"tool_name": "bash", "tool_input": {}}))
    assert d.decision == "deny" and "saw bash" in d.reason


def test_run_matcher_filters(monkeypatch, tmp_path):
    s = _write(tmp_path, "deny.py",
               "import sys,json; print(json.dumps({'permissionDecision':'deny'}))\n")
    _hook_settings(monkeypatch, "PreToolUse", f'"{sys.executable}" "{s}"', matcher="edit_file")
    d = asyncio.run(hooks.run("PreToolUse", {"tool_name": "bash"}))
    assert d.decision is None          # matcher didn't match -> hook never ran


def test_run_timeout_denies_blocking_event(monkeypatch, tmp_path):
    s = _write(tmp_path, "hang.py", "import time; time.sleep(30)\n")
    _hook_settings(monkeypatch, "PreToolUse", f'"{sys.executable}" "{s}"', timeout=1)
    d = asyncio.run(hooks.run("PreToolUse", {"tool_name": "bash"}))
    assert d.decision == "deny" and "timed out" in d.reason.lower()


def test_run_timeout_is_open_for_observational_event(monkeypatch, tmp_path):
    s = _write(tmp_path, "hang.py", "import time; time.sleep(30)\n")
    _hook_settings(monkeypatch, "PostToolUse", f'"{sys.executable}" "{s}"', timeout=1)
    d = asyncio.run(hooks.run("PostToolUse", {"tool_name": "bash"}))
    assert d.decision is None


def test_run_missing_command_denies_blocking_event(monkeypatch):
    _hook_settings(monkeypatch, "PreToolUse", "definitely-not-a-real-binary-xyz")
    d = asyncio.run(hooks.run("PreToolUse", {"tool_name": "bash"}))
    assert d.decision == "deny"


def test_run_strips_secret_env(monkeypatch, tmp_path):
    monkeypatch.setenv("OCD_API_TOKEN", "TOKLEAK-hook")
    s = _write(tmp_path, "env.py",
               "import os,json\n"
               "print(json.dumps({'additionalContext': 'tok=' + os.environ.get('OCD_API_TOKEN','')}))\n")
    _hook_settings(monkeypatch, "SessionStart", f'"{sys.executable}" "{s}"')
    d = asyncio.run(hooks.run("SessionStart", {}))
    assert "TOKLEAK-hook" not in d.context and "tok=" in d.context


def test_run_caps_timeout_at_max(monkeypatch, tmp_path):
    s = _write(tmp_path, "ok.py", "print('{}')\n")
    _hook_settings(monkeypatch, "SessionStart", f'"{sys.executable}" "{s}"', timeout=99999)
    # must not raise; the cap is applied internally
    assert asyncio.run(hooks.run("SessionStart", {})).decision is None
