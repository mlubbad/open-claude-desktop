"""JSON validate + pretty-print plugin."""
import json

NAME = "json_tool"
DESCRIPTION = "Validate and pretty-print a JSON string."

TOOL = {
    "type": "function",
    "function": {
        "name": "json_tool",
        "description": "Validate a JSON string and return it pretty-printed, or an "
                       "error describing what is malformed.",
        "parameters": {
            "type": "object",
            "properties": {"text": {"type": "string", "description": "JSON to check."}},
            "required": ["text"],
        },
    },
}


def run(args: dict) -> str:
    text = str(args.get("text", ""))
    if not text.strip():
        return "No JSON provided."
    try:
        obj = json.loads(text)
        pretty = json.dumps(obj, indent=2, ensure_ascii=False)
        kind = type(obj).__name__
        return f"Valid JSON ({kind}):\n{pretty[:2000]}"
    except json.JSONDecodeError as e:
        return f"Invalid JSON: {e.msg} at line {e.lineno}, column {e.colno}."
