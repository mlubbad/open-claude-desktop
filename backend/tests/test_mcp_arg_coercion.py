"""Schema-guided coercion of LLM-emitted MCP tool arguments.

Seen in the wild: a model calling a desktop-automation MCP tool with
``{"loc": "[0, 0]"}`` — the array stringified — which the server's pydantic
validation rejected verbatim, seven rounds in a row, burning the turn's whole step
budget. ``coerce_args_to_schema`` repairs exactly this class of mistake (stringified
arrays/objects/ints/floats/bools) against the tool's declared inputSchema, and
``call_mcp`` applies it before dispatch — for every current and future connector.
"""
from ocd_core import integrations
from ocd_core.integrations import coerce_args_to_schema


def _schema(**props):
    return {"type": "object", "properties": props}


def test_stringified_array_is_coerced():
    # The exact failure from the field: loc sent as the STRING "[0, 0]".
    schema = _schema(loc={"type": "array", "items": {"type": "integer"}})
    assert coerce_args_to_schema({"loc": "[0, 0]"}, schema) == {"loc": [0, 0]}


def test_stringified_scalars_are_coerced():
    schema = _schema(use_sampling={"type": "boolean"},
                     duration={"type": "integer"},
                     scale={"type": "number"})
    out = coerce_args_to_schema(
        {"use_sampling": "true", "duration": "3", "scale": "2.5"}, schema)
    assert out == {"use_sampling": True, "duration": 3, "scale": 2.5}


def test_stringified_object_is_coerced():
    schema = _schema(opts={"type": "object"})
    assert coerce_args_to_schema({"opts": '{"a": 1}'}, schema) == {"opts": {"a": 1}}


def test_union_type_uses_first_concrete_type():
    schema = _schema(loc={"type": ["array", "null"]})
    assert coerce_args_to_schema({"loc": "[1, 2]"}, schema) == {"loc": [1, 2]}


def test_untouchable_values_pass_through():
    schema = _schema(loc={"type": "array"}, label={"type": "integer"},
                     name={"type": "string"}, flag={"type": "boolean"})
    args = {"loc": "New Tab",     # not JSON — leave it; the server's error guides
            "label": "New Tab",   # not an int — leave it
            "name": "x",          # string param stays a string
            "flag": "yes",        # not true/false — leave it
            "extra": "[1]"}       # not in the schema — leave it
    assert coerce_args_to_schema(args, schema) == args


def test_already_typed_values_untouched():
    schema = _schema(loc={"type": "array"}, n={"type": "integer"})
    args = {"loc": [0, 0], "n": 3}
    assert coerce_args_to_schema(args, schema) == args


def test_json_of_wrong_shape_is_not_coerced():
    # "5" parses as JSON but is not an array — must NOT become loc=5.
    schema = _schema(loc={"type": "array"})
    assert coerce_args_to_schema({"loc": "5"}, schema) == {"loc": "5"}


def test_degenerate_schema_is_safe():
    assert coerce_args_to_schema({"a": "[1]"}, {}) == {"a": "[1]"}
    assert coerce_args_to_schema({"a": "[1]"}, {"properties": "bogus"}) == {"a": "[1]"}


def test_call_mcp_coerces_before_dispatch(monkeypatch):
    """End-to-end through call_mcp: the registry receives the REPAIRED args."""
    server = {"id": "desktop", "name": "Desktop", "transport": "stdio",
              "command": "fake", "tools": [
                  {"name": "Click",
                   "inputSchema": _schema(loc={"type": "array"},
                                          double={"type": "boolean"})}]}
    monkeypatch.setattr(integrations.config, "STDIO_MCP_ENABLED", True)
    monkeypatch.setattr(integrations, "_load_mcp_servers", lambda: [server])
    monkeypatch.setattr(integrations, "_resolve_cfg", lambda s: s)
    seen = {}

    def _fake_call(cfg, tool, args):
        seen["tool"], seen["args"] = tool, args
        return "clicked"

    monkeypatch.setattr(integrations.mcp_registry.registry, "call", _fake_call)
    out = integrations.call_mcp("mcp_desktop_Click", {"loc": "[10, 20]", "double": "true"})
    assert out == "clicked"
    assert seen["tool"] == "Click"
    assert seen["args"] == {"loc": [10, 20], "double": True}
