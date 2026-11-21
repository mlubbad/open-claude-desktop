"""Marketplace plugin — Base64 encode / decode (UTF-8 text)."""
import base64
import binascii

NAME = "base64_tool"
DESCRIPTION = "Encode text to Base64 or decode Base64 back to text."
CATEGORY = "Encoding"

TOOL = {
    "type": "function",
    "function": {
        "name": "base64_tool",
        "description": "Base64-encode or -decode UTF-8 text. Set direction to 'encode' "
                       "or 'decode'.",
        "parameters": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "The input text."},
                "direction": {"type": "string", "enum": ["encode", "decode"],
                              "description": "encode text→base64, or decode base64→text."},
            },
            "required": ["text", "direction"],
        },
    },
}


def run(args: dict) -> str:
    text = str(args.get("text", ""))
    direction = str(args.get("direction", "encode")).strip().lower()
    try:
        if direction == "encode":
            return base64.b64encode(text.encode("utf-8")).decode("ascii")
        if direction == "decode":
            # Strict on purpose: non-alphabet bytes (including line-wrapped
            # input) are rejected rather than repaired.
            return base64.b64decode(text.encode("ascii"), validate=True).decode("utf-8")
        return "Direction must be 'encode' or 'decode'."
    except (binascii.Error, UnicodeDecodeError, ValueError) as e:
        return f"Could not {direction}: {e}"
