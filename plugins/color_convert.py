"""Marketplace plugin — convert colors between HEX and RGB."""
import re

NAME = "color_convert"
DESCRIPTION = "Convert a color between HEX (#rrggbb) and RGB (r,g,b)."
CATEGORY = "Design"

TOOL = {
    "type": "function",
    "function": {
        "name": "color_convert",
        "description": "Convert a color between HEX and RGB. Accepts '#1e90ff' or "
                       "'30,144,255' and returns the other form.",
        "parameters": {
            "type": "object",
            "properties": {"color": {"type": "string",
                                     "description": "A HEX (#rrggbb) or RGB (r,g,b) color."}},
            "required": ["color"],
        },
    },
}

_HEX = re.compile(r"^#?([0-9a-fA-F]{6})$")
_RGB = re.compile(r"^\s*(\d{1,3})\s*,\s*(\d{1,3})\s*,\s*(\d{1,3})\s*$")


def run(args: dict) -> str:
    color = str(args.get("color", "")).strip()
    m = _HEX.match(color)
    if m:
        h = m.group(1)
        r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
        return f"#{h.lower()} = rgb({r}, {g}, {b})"
    m = _RGB.match(color)
    if m:
        r, g, b = (int(x) for x in m.groups())
        if max(r, g, b) > 255:
            return "RGB components must be 0–255."
        return f"rgb({r}, {g}, {b}) = #{r:02x}{g:02x}{b:02x}"
    return f"Could not parse color '{color}'. Use '#rrggbb' or 'r,g,b'."
