"""Tests for the frontend-local pure formatters (Phase 4 Task 3).

Assertions reflect the VERBATIM behavior of the backend source functions
they were copied from (ocd_core.util.fmt_bytes and
ocd_core.agent._strip_answer_label) — the source is the contract.
"""
from aj360_app.format import fmt_bytes, strip_answer_label


def test_fmt_bytes_zero_and_falsy():
    # Falsy values (0, None) short-circuit to "0 B".
    assert fmt_bytes(0) == "0 B"
    assert fmt_bytes(None) == "0 B"


def test_fmt_bytes_scales_across_unit_boundaries():
    assert fmt_bytes(1) == "1.0 B"
    assert fmt_bytes(1023) == "1023.0 B"
    assert fmt_bytes(1024) == "1.0 KB"
    assert fmt_bytes(1536) == "1.5 KB"
    assert fmt_bytes(1024 * 1024) == "1.0 MB"
    assert fmt_bytes(1024 * 1024 * 1024) == "1.0 GB"
    assert fmt_bytes(1024 ** 4) == "1.0 TB"


def test_fmt_bytes_caps_at_tb():
    # TB is the largest unit; values beyond stay in TB (no PB rollover).
    assert fmt_bytes(1024 ** 5) == "1024.0 TB"


def test_strip_answer_label_passthrough_plain_text():
    assert strip_answer_label("Just the answer.") == "Just the answer."


def test_strip_answer_label_removes_leading_label():
    assert strip_answer_label("Final Answer:\nThe revenue was 5M.") == "The revenue was 5M."
    assert strip_answer_label("Corrected Answer\nThe revenue was 5M.") == "The revenue was 5M."


def test_strip_answer_label_removes_markdown_heading_and_bold():
    assert strip_answer_label("## Verified Answer:\n\nDone.") == "Done."
    assert strip_answer_label("**Improved Answer**\nHi") == "Hi"


def test_strip_answer_label_does_not_strip_inline_mention():
    # "final answer" mid-sentence is not a leading label and must pass through.
    assert strip_answer_label("The final answer is 42.") == "The final answer is 42."


def test_strip_answer_label_requires_trailing_newline():
    # Without a newline after the label, nothing is stripped.
    assert strip_answer_label("Answer: nope") == "Answer: nope"
