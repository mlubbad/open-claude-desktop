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


# ------------------------- F-03: word_count whitespace ------------------------- #

def _counts(text: str) -> str:
    return _plugin("word_count").run({"text": text})


def test_word_count_empty_string():
    assert _counts("") == ("words: 0\nlines: 0\ncharacters: 0\n"
                           "characters (no whitespace): 0")


def test_word_count_spaces_only():
    assert _counts("   ") == ("words: 0\nlines: 1\ncharacters: 3\n"
                              "characters (no whitespace): 0")


def test_word_count_lf():
    assert _counts("a\nb") == ("words: 2\nlines: 2\ncharacters: 3\n"
                               "characters (no whitespace): 2")


def test_word_count_crlf():
    assert _counts("a\r\nb") == ("words: 2\nlines: 2\ncharacters: 4\n"
                                 "characters (no whitespace): 2")


def test_word_count_bare_cr():
    assert _counts("a\rb") == ("words: 2\nlines: 2\ncharacters: 3\n"
                               "characters (no whitespace): 2")


def test_word_count_tabs():
    assert _counts("a\tb") == ("words: 2\nlines: 1\ncharacters: 3\n"
                               "characters (no whitespace): 2")


def test_word_count_non_breaking_space():
    assert _counts("a b") == ("words: 2\nlines: 1\ncharacters: 3\n"
                                   "characters (no whitespace): 2")


def test_word_count_unicode_whitespace():
    # EM SPACE (U+2003) and IDEOGRAPHIC SPACE (U+3000) are whitespace too.
    assert _counts("a b　c") == ("words: 3\nlines: 1\ncharacters: 5\n"
                                          "characters (no whitespace): 3")


def test_word_count_trailing_newline_adds_no_line():
    assert _counts("line\n") == ("words: 1\nlines: 1\ncharacters: 5\n"
                                 "characters (no whitespace): 4")


def test_word_count_blank_line_between_content():
    assert _counts("a\n\nb") == ("words: 2\nlines: 3\ncharacters: 4\n"
                                 "characters (no whitespace): 2")


# ------------------------ F-04: color_convert rgb() syntax ------------------------ #

def _color(value: str) -> str:
    return _plugin("color_convert").run({"color": value})


def test_color_hex_to_rgb():
    assert _color("#1e90ff") == "#1e90ff = rgb(30, 144, 255)"


def test_color_hex_without_hash():
    assert _color("1e90ff") == "#1e90ff = rgb(30, 144, 255)"


def test_color_uppercase_hex():
    assert _color("#1E90FF") == "#1e90ff = rgb(30, 144, 255)"


def test_color_bare_rgb_triple():
    assert _color("30,144,255") == "rgb(30, 144, 255) = #1e90ff"


def test_color_round_trips_its_own_rgb_output():
    assert _color("rgb(30, 144, 255)") == "rgb(30, 144, 255) = #1e90ff"


def test_color_rgb_wrapper_case_and_whitespace():
    assert _color("RGB( 30 ,144,  255 )") == "rgb(30, 144, 255) = #1e90ff"


def test_color_component_above_255_rejected():
    assert _color("rgb(300, 0, 0)") == "RGB components must be 0–255."
    assert _color("999,0,0") == "RGB components must be 0–255."


def test_color_negative_component_rejected():
    assert _color("-1,0,0").startswith("Could not parse color")


def test_color_missing_component_rejected():
    assert _color("rgb(30, 144)").startswith("Could not parse color")


def test_color_extra_component_rejected():
    assert _color("rgb(30, 144, 255, 10)").startswith("Could not parse color")


def test_color_unbalanced_wrapper_rejected():
    assert _color("rgb(30, 144, 255").startswith("Could not parse color")
    assert _color("30, 144, 255)").startswith("Could not parse color")


def test_color_malformed_trailing_input_rejected():
    assert _color("30,144,255 junk").startswith("Could not parse color")


# ------------------- roman_numeral: regression pins (non-finding) ------------------- #
# The 2026-07-25 review exhaustively verified this plugin; these tests pin the
# verified behavior so it stays green.

def test_roman_numeral_round_trips_full_range():
    mod = _plugin("roman_numeral")
    for n in range(1, 4000):
        assert mod._from_roman(mod._to_roman(n)) == n


def test_roman_numeral_run_converts_both_ways():
    mod = _plugin("roman_numeral")
    assert mod.run({"value": "1994"}) == "1994 = MCMXCIV"
    assert mod.run({"value": "mcmxciv"}) == "MCMXCIV = 1994"


def test_roman_numeral_rejects_malformed_and_out_of_range():
    mod = _plugin("roman_numeral")
    assert mod.run({"value": "IIII"}).startswith("Could not convert")
    assert mod.run({"value": "0"}).startswith("Could not convert")
    assert mod.run({"value": "4000"}).startswith("Could not convert")
