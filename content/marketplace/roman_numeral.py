"""Marketplace plugin — convert between integers and Roman numerals."""
NAME = "roman_numeral"
DESCRIPTION = "Convert an integer (1–3999) to a Roman numeral, or a Roman numeral to an integer."
CATEGORY = "Math"

TOOL = {
    "type": "function",
    "function": {
        "name": "roman_numeral",
        "description": "Convert between integers (1–3999) and Roman numerals. Provide 'value' "
                       "as either a number or a Roman numeral string.",
        "parameters": {
            "type": "object",
            "properties": {"value": {"type": "string",
                                     "description": "An integer 1–3999 or a Roman numeral."}},
            "required": ["value"],
        },
    },
}

_TABLE = [(1000, "M"), (900, "CM"), (500, "D"), (400, "CD"), (100, "C"), (90, "XC"),
          (50, "L"), (40, "XL"), (10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I")]
_VALUES = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 500, "M": 1000}


def _to_roman(n: int) -> str:
    if not 1 <= n <= 3999:
        raise ValueError("integer must be between 1 and 3999")
    out = []
    for value, sym in _TABLE:
        while n >= value:
            out.append(sym)
            n -= value
    return "".join(out)


def _from_roman(s: str) -> int:
    s = s.upper()
    if any(c not in _VALUES for c in s):
        raise ValueError("not a Roman numeral")
    total, prev = 0, 0
    for c in reversed(s):
        v = _VALUES[c]
        total += -v if v < prev else v
        prev = max(prev, v)
    if _to_roman(total) != s:
        raise ValueError("not a well-formed Roman numeral")
    return total


def run(args: dict) -> str:
    value = str(args.get("value", "")).strip()
    if not value:
        return "No value provided."
    try:
        if value.lstrip("-").isdigit():
            return f"{int(value)} = {_to_roman(int(value))}"
        return f"{value.upper()} = {_from_roman(value)}"
    except ValueError as e:
        return f"Could not convert '{value}': {e}"
