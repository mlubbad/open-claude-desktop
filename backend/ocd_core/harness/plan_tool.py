# backend/ocd_core/harness/plan_tool.py
"""Model-driven task plan for a workspace turn. One Plan per turn; the agent calls the
`task_plan` tool to set the item list and update item statuses. The loop emits the
snapshot as `plan_update` events for the UI plan card."""
from __future__ import annotations

_STATUSES = {"pending", "in_progress", "completed"}


class Plan:
    def __init__(self):
        self._items: list[dict] = []

    def apply(self, args: dict) -> dict:
        op = (args or {}).get("op")
        if op == "set":
            items = args.get("items") or []
            self._items = [
                {"id": i + 1, "subject": str(it.get("subject", "")).strip(),
                 "status": it.get("status", "pending") if it.get("status") in _STATUSES else "pending"}
                for i, it in enumerate(items)]
            return {"ok": True, "count": len(self._items)}
        if op == "update":
            iid = args.get("id")
            status = args.get("status")
            if status not in _STATUSES:
                return {"ok": False, "error": f"bad status: {status}"}
            for it in self._items:
                if it["id"] == iid:
                    it["status"] = status
                    return {"ok": True}
            return {"ok": False, "error": f"no item {iid}"}
        return {"ok": False, "error": f"unknown op: {op}"}

    def snapshot(self) -> list[dict]:
        return [dict(it) for it in self._items]


PLAN_TOOL_SPEC = {"type": "function", "function": {
    "name": "task_plan",
    "description": "Maintain a short task plan for multi-step work. op=set replaces the "
                   "item list ([{subject}]); op=update sets one item's status "
                   "(pending|in_progress|completed). Keep it to 3-8 concrete steps and "
                   "update statuses as you go so the user can follow along.",
    "parameters": {"type": "object", "properties": {
        "op": {"type": "string", "enum": ["set", "update"]},
        "items": {"type": "array", "items": {"type": "object", "properties": {
            "subject": {"type": "string"}}}},
        "id": {"type": "integer"},
        "status": {"type": "string", "enum": ["pending", "in_progress", "completed"]}},
        "required": ["op"]}}}
