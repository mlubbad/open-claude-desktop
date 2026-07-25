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
