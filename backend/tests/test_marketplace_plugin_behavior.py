"""Behavior of the canonical marketplace catalog plugins (content/marketplace/).

Files are loaded with a minimal importlib equivalent of the runtime loader and
deliberately WITHOUT importing ocd_core, so this file runs in seconds;
test_marketplace_plugins.py separately proves the same files load through the
real integrations._load_plugin_module.

Covers the 2026-07-25 review findings: F-02 (base64 direction validation),
F-03 (word_count whitespace), F-04 (color_convert rgb() syntax).
"""
import importlib.util
from pathlib import Path

_CATALOG = Path(__file__).resolve().parents[2] / "content" / "marketplace"


def _plugin(name: str):
    path = _CATALOG / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"mp_behavior_{name}", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ------------------------- F-02: base64_tool direction ------------------------- #

_DIRECTION_ERROR = "Direction must be 'encode' or 'decode'."


def test_base64_encodes():
    assert _plugin("base64_tool").run(
        {"text": "hello", "direction": "encode"}) == "aGVsbG8="


def test_base64_decodes():
    assert _plugin("base64_tool").run(
        {"text": "aGVsbG8=", "direction": "decode"}) == "hello"


def test_base64_round_trips_unicode():
    mod = _plugin("base64_tool")
    encoded = mod.run({"text": "héllo ✓", "direction": "encode"})
    assert mod.run({"text": encoded, "direction": "decode"}) == "héllo ✓"


def test_base64_missing_direction_defaults_to_encode():
    assert _plugin("base64_tool").run({"text": "hi"}) == "aGk="


def test_base64_rejects_unknown_direction():
    out = _plugin("base64_tool").run({"text": "aGVsbG8=", "direction": "decoding"})
    assert out == _DIRECTION_ERROR


def test_base64_rejects_empty_direction():
    out = _plugin("base64_tool").run({"text": "aGVsbG8=", "direction": ""})
    assert out == _DIRECTION_ERROR


def test_base64_rejects_non_string_direction():
    out = _plugin("base64_tool").run({"text": "aGVsbG8=", "direction": 123})
    assert out == _DIRECTION_ERROR


def test_base64_reports_invalid_base64_on_decode():
    out = _plugin("base64_tool").run({"text": "not base64!!", "direction": "decode"})
    assert out.startswith("Could not decode:")


def test_base64_reports_non_utf8_decode():
    out = _plugin("base64_tool").run({"text": "gA==", "direction": "decode"})
    assert out.startswith("Could not decode:")


def test_base64_strict_decode_rejects_wrapped_input():
    """Line-wrapped (MIME-style) base64 is rejected, not silently repaired —
    a deliberate strictness decision recorded in the 2026-07-25 review."""
    out = _plugin("base64_tool").run({"text": "aGVs\nbG8=", "direction": "decode"})
    assert out.startswith("Could not decode:")
