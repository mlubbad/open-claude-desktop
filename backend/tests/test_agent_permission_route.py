"""The permission reply endpoint: validation + 404 when nothing is pending."""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from app.routes import agent as agent_route
    app = FastAPI()
    app.include_router(agent_route.router)
    return TestClient(app)


def test_reply_unknown_turn_is_404(client):
    r = client.post("/agent/turn/nope/permission",
                    json={"tool_call_id": "c1", "decision": "approve"})
    assert r.status_code == 404


def test_reply_bad_decision_is_422(client):
    r = client.post("/agent/turn/t1/permission",
                    json={"tool_call_id": "c1", "decision": "maybe"})
    assert r.status_code == 422


def test_reply_resolves_a_waiting_prompt(client):
    # Seed a pending approval directly, then resolve it via the endpoint.
    import asyncio

    from ocd_core import permissions

    async def seed_and_call():
        waiter = asyncio.create_task(
            permissions.registry.wait("t1", "c1", timeout=2))
        for _ in range(200):
            if permissions.registry.pending("t1"):
                break
            await asyncio.sleep(0.005)
        r = client.post("/agent/turn/t1/permission",
                        json={"tool_call_id": "c1", "decision": "approve"})
        approved = await waiter
        return r, approved

    r, approved = asyncio.run(seed_and_call())
    assert r.status_code == 200
    assert r.json() == {"resolved": True, "decision": "approve"}
    assert approved is True
