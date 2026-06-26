"""Percent-change / growth calculator plugin."""

NAME = "percent_change"
DESCRIPTION = "Percent change between two numbers (old -> new)."

TOOL = {
    "type": "function",
    "function": {
        "name": "percent_change",
        "description": "Compute the percent change from `old` to `new`, plus the "
                       "absolute delta. Useful for period-over-period metrics.",
        "parameters": {
            "type": "object",
            "properties": {
                "old": {"type": "number", "description": "Baseline / previous value."},
                "new": {"type": "number", "description": "Current value."},
            },
            "required": ["old", "new"],
        },
    },
}


def run(args: dict) -> str:
    try:
        old = float(args["old"])
        new = float(args["new"])
    except Exception:
        return "Provide numeric `old` and `new`."
    delta = new - old
    if old == 0:
        pct = "undefined (baseline is 0)"
    else:
        pct = f"{(delta / abs(old)) * 100:+.2f}%"
    return f"{old:,g} → {new:,g}: change {delta:+,g} ({pct})"
