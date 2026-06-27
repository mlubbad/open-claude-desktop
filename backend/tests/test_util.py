"""Unit tests for ocd_core.util — pure helpers shared by both app surfaces.

These encode the EXACT pre-refactor behavior ported verbatim from
aj360_app/aj360_app/core.py. The original implementation is the contract.
"""
from ocd_core import util


def test_slugify():
    assert util.slugify("Hello World!") == "hello-world"
    assert util.slugify("  A/B  C ") == "a-b-c"
    assert util.slugify("") == "untitled"


def test_fmt_bytes():
    assert util.fmt_bytes(0) == "0 B"
    assert util.fmt_bytes(1024) == "1.0 KB"
    assert util.fmt_bytes(1024 ** 3) == "1.0 GB"


def test_chunk_id_is_stable_and_content_sensitive():
    a = util.chunk_id("f.md", 3, "hello")
    assert a == util.chunk_id("f.md", 3, "hello")
    assert a != util.chunk_id("f.md", 3, "world")


class _Field:
    """Minimal stand-in for a BigQuery SchemaField (attribute access)."""

    def __init__(self, name, field_type, mode=None, fields=None):
        self.name = name
        self.field_type = field_type
        self.mode = mode
        self.fields = fields


def test_flatten_fields_dotted_paths():
    # NOTE (adjusted from the task's draft assertion to match the REAL
    # implementation in core.py): _flatten_fields operates on objects with
    # `.name`/`.field_type`/`.mode`/`.fields` attributes (BQ SchemaField), NOT
    # dicts, and returns a list of (name, type, mode) TUPLES, not bare names.
    fields = [
        _Field("a", "STRING"),
        _Field("rec", "RECORD", fields=[_Field("b", "INT64")]),
    ]
    result = util.flatten_fields(fields)
    assert result == [
        ("a", "STRING", "NULLABLE"),
        ("rec", "RECORD", "NULLABLE"),
        ("rec.b", "INT64", "NULLABLE"),
    ]
    # Dotted paths are exposed in the first tuple element.
    assert {name for name, _type, _mode in result} == {"a", "rec", "rec.b"}
