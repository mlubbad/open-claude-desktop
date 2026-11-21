import importlib


def test_get_settings_defaults(monkeypatch, tmp_path):
    monkeypatch.setenv("OCD_DATA_DIR", str(tmp_path))
    import ocd_core.config as c
    import ocd_core.settings as s
    importlib.reload(c)
    importlib.reload(s)
    got = s.get_settings()
    # Parity with the original core.get_settings(): a missing settings.json
    # yields DEFAULT_SETTINGS verbatim (model=AGENT_MODEL, effort="High",
    # theme="light"); effort is one of the four EFFORT_LEVELS.
    assert got["effort"] in ("Low", "Medium", "High", "Max")
    assert got["effort"] == "High"
    assert "model" in got and "theme" in got
    assert got["model"] == c.AGENT_MODEL
    assert got["theme"] == "light"


def test_save_then_get_roundtrip(monkeypatch, tmp_path):
    monkeypatch.setenv("OCD_DATA_DIR", str(tmp_path))
    import ocd_core.config as c
    import ocd_core.settings as s
    importlib.reload(c)
    importlib.reload(s)
    s.save_settings({"effort": "Low"})
    assert s.get_settings()["effort"] == "Low"


def test_save_settings_ignores_unknown_keys(monkeypatch, tmp_path):
    # Original save_settings only persists keys present in DEFAULT_SETTINGS.
    monkeypatch.setenv("OCD_DATA_DIR", str(tmp_path))
    import ocd_core.config as c
    import ocd_core.settings as s
    importlib.reload(c)
    importlib.reload(s)
    out = s.save_settings({"effort": "Medium", "bogus": "nope"})
    assert out["effort"] == "Medium"
    assert "bogus" not in out
    assert "bogus" not in s.get_settings()


def test_custom_and_hidden_models_roundtrip(monkeypatch, tmp_path):
    # The per-provider custom/hidden model lists persist like visible_models (free-form
    # dicts, no enum clamping), so a user's added/removed models survive a restart.
    monkeypatch.setenv("OCD_DATA_DIR", str(tmp_path))
    import ocd_core.config as c
    import ocd_core.settings as s
    importlib.reload(c)
    importlib.reload(s)
    assert s.get_settings()["custom_models"] == {} and s.get_settings()["hidden_models"] == {}
    s.save_settings({"custom_models": {"ollama": ["qwen2.5:14b"]},
                     "hidden_models": {"ollama": ["deepseek-r1"]}})
    got = s.get_settings()
    assert got["custom_models"] == {"ollama": ["qwen2.5:14b"]}
    assert got["hidden_models"] == {"ollama": ["deepseek-r1"]}


def test_legacy_reasoning_level_maps_to_effort(monkeypatch, tmp_path):
    # Backward-compat: older files stored "reasoning_level"; get_settings maps
    # it onto "effort" when "effort" is absent.
    monkeypatch.setenv("OCD_DATA_DIR", str(tmp_path))
    import ocd_core.config as c
    import ocd_core.settings as s
    importlib.reload(c)
    importlib.reload(s)
    c.SETTINGS_FILE.write_text('{"reasoning_level": "Max"}', encoding="utf-8")
    assert s.get_settings()["effort"] == "Max"


def test_invalid_effort_clamps_to_high(monkeypatch, tmp_path):
    # An effort outside EFFORT_LEVELS falls back to "High".
    monkeypatch.setenv("OCD_DATA_DIR", str(tmp_path))
    import ocd_core.config as c
    import ocd_core.settings as s
    importlib.reload(c)
    importlib.reload(s)
    c.SETTINGS_FILE.write_text('{"effort": "Bogus"}', encoding="utf-8")
    assert s.get_settings()["effort"] == "High"
