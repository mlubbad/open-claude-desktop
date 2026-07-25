# backend/tests/test_harness_hooks.py
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
