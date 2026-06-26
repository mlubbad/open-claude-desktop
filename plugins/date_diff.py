"""Date arithmetic plugin — difference between dates, or shift a date by days."""
from datetime import date, datetime, timedelta

NAME = "date_diff"
DESCRIPTION = "Days between two dates, or shift a date by N days."

TOOL = {
    "type": "function",
    "function": {
        "name": "date_diff",
        "description": "Date math. Mode 'between': days between start and end "
                       "(YYYY-MM-DD). Mode 'shift': add `days` to start.",
        "parameters": {
            "type": "object",
            "properties": {
                "mode": {"type": "string", "enum": ["between", "shift"]},
                "start": {"type": "string", "description": "Start date YYYY-MM-DD."},
                "end": {"type": "string", "description": "End date YYYY-MM-DD (mode=between)."},
                "days": {"type": "integer", "description": "Days to add (mode=shift)."},
            },
            "required": ["mode", "start"],
        },
    },
}


def _parse(s: str) -> date:
    return datetime.strptime(str(s).strip()[:10], "%Y-%m-%d").date()


def run(args: dict) -> str:
    mode = args.get("mode", "between")
    try:
        start = _parse(args["start"])
        if mode == "shift":
            n = int(args.get("days", 0))
            return f"{start.isoformat()} + {n} days = {(start + timedelta(days=n)).isoformat()}"
        end = _parse(args["end"])
        return f"{(end - start).days} days between {start.isoformat()} and {end.isoformat()}"
    except Exception as e:
        return f"date_diff error: {e}"
