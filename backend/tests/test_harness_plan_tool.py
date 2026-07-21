# backend/tests/test_harness_plan_tool.py
from ocd_core.harness import plan_tool


def test_set_plan_creates_items():
    plan = plan_tool.Plan()
    out = plan.apply({"op": "set", "items": [
        {"subject": "read code"}, {"subject": "write test"}]})
    assert out["ok"] is True
    assert [i["status"] for i in plan.snapshot()] == ["pending", "pending"]
    assert plan.snapshot()[0]["id"] == 1


def test_update_status():
    plan = plan_tool.Plan()
    plan.apply({"op": "set", "items": [{"subject": "a"}, {"subject": "b"}]})
    plan.apply({"op": "update", "id": 1, "status": "completed"})
    assert plan.snapshot()[0]["status"] == "completed"


def test_update_bad_status_rejected():
    plan = plan_tool.Plan()
    plan.apply({"op": "set", "items": [{"subject": "a"}]})
    out = plan.apply({"op": "update", "id": 1, "status": "banana"})
    assert out["ok"] is False


def test_tool_spec_name():
    assert plan_tool.PLAN_TOOL_SPEC["function"]["name"] == "task_plan"


def test_plan_apply_bad_items_returns_error():
    plan = plan_tool.Plan()
    assert plan.apply({"op": "set", "items": "nope"})["ok"] is False
    assert plan.apply({"op": "set", "items": ["not-a-dict"]})["ok"] is False


def test_plan_update_string_id_coerced():
    plan = plan_tool.Plan()
    plan.apply({"op": "set", "items": [{"subject": "a"}]})
    out = plan.apply({"op": "update", "id": "1", "status": "completed"})
    assert out["ok"] is True and plan.snapshot()[0]["status"] == "completed"
