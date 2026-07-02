import json

import httpx
import ocd_app.api_client as api_client
import pytest
import respx


def _sse(*events: dict) -> bytes:
    """Serialize event dicts as an SSE body the way backend/app/sse.py does."""
    frames = []
    for ev in events:
        frames.append(f"event: {ev['type']}\ndata: {json.dumps(ev)}\n")
    return ("\n".join(frames) + "\n").encode()


@respx.mock
async def test_configure_token_sets_bearer_header():
    api_client.configure(token="tok-123")
    try:
        proj = respx.get("http://test/projects").mock(
            return_value=httpx.Response(200, json=[]))
        await api_client.list_projects()
        assert proj.calls.last.request.headers["authorization"] == "Bearer tok-123"
    finally:
        api_client.configure(token=None)  # don't leak into other tests


@respx.mock
async def test_anonymous_has_no_auth_header():
    route = respx.get("http://test/projects").mock(
        return_value=httpx.Response(200, json=[{"id": "p1"}]))
    out = await api_client.list_projects()
    assert out == [{"id": "p1"}]
    assert "authorization" not in route.calls.last.request.headers


@respx.mock
async def test_list_project_cards_hits_view_param():
    route = respx.get("http://test/projects", params={"view": "card"}).mock(
        return_value=httpx.Response(200, json=[{"id": "p1", "name": "P", "desc": "d",
                                                "updated": "today", "href": "/project/p1"}]))
    cards = await api_client.list_project_cards()
    assert cards[0]["href"] == "/project/p1"
    assert route.called


@respx.mock
async def test_get_project_memory_returns_tuple():
    respx.get("http://test/projects/p1/memory").mock(
        return_value=httpx.Response(200, json={"content": "notes", "updated_rel": "2h ago"}))
    text, rel = await api_client.get_project_memory("p1")
    assert text == "notes"
    assert rel == "2h ago"


@respx.mock
async def test_upload_file_sends_multipart():
    route = respx.post("http://test/projects/p1/files").mock(
        return_value=httpx.Response(200, json={"ok": True, "name": "a.csv", "chunks": 3}))
    out = await api_client.upload_file("p1", "a.csv", b"col\n1\n")
    assert out["chunks"] == 3
    assert route.calls.last.request.headers["content-type"].startswith("multipart/form-data")


@respx.mock
async def test_execute_sql_posts_body():
    route = respx.post("http://test/sql/execute").mock(
        return_value=httpx.Response(200, json={"ok": True, "rows": [], "columns": [],
                                               "total_rows": 0, "bytes": 0, "agent_text": ""}))
    out = await api_client.execute_sql("SELECT 1", "p1")
    assert out["ok"] is True
    assert json.loads(route.calls.last.request.content) == {"sql": "SELECT 1", "project": "p1"}


@respx.mock
async def test_non_2xx_raises_apierror():
    respx.get("http://test/projects/missing").mock(return_value=httpx.Response(404, json={"detail": "not found"}))
    with pytest.raises(api_client.ApiError) as ei:
        await api_client.get_project("missing")
    assert ei.value.status == 404


@respx.mock
async def test_run_agent_stream_parses_real_vocab_and_stops_on_done():
    body = _sse(
        {"type": "think_open", "phase": "plan"},
        {"type": "delta", "scope": "think", "text": "Let me check"},
        {"type": "think_close", "elapsed": 2},
        {"type": "tool", "id": "t1", "name": "run_sql", "icon": "database",
         "label_running": "Running", "label_done": "Ran", "input": "SELECT 1"},
        {"type": "tool_result", "id": "t1", "summary": "1 row"},
        {"type": "table", "total": 1, "bytes": 10, "columns": ["n"], "rows": [{"n": 1}]},
        {"type": "answer_open"},
        {"type": "delta", "scope": "answer", "text": "The answer"},
        {"type": "done"},
    )
    respx.post("http://test/agent/turn").mock(
        return_value=httpx.Response(200, headers={"content-type": "text/event-stream"}, content=body))

    got = [ev async for ev in api_client.run_agent_stream({"goal": "hi", "model": "glm-4-plus"})]
    types = [e["type"] for e in got]
    assert types == ["think_open", "delta", "think_close", "tool", "tool_result",
                     "table", "answer_open", "delta"]   # 'done' consumed, not yielded
    assert got[3]["id"] == "t1" and got[3]["icon"] == "database"
    assert got[5]["columns"] == ["n"]


@respx.mock
async def test_run_agent_stream_yields_error_frame():
    body = _sse({"type": "error", "text": "boom"}, {"type": "done"})
    respx.post("http://test/agent/turn").mock(
        return_value=httpx.Response(200, headers={"content-type": "text/event-stream"}, content=body))
    got = [ev async for ev in api_client.run_agent_stream({"goal": "x", "model": "m"})]
    assert got == [{"type": "error", "text": "boom"}]


@respx.mock
async def test_run_agent_stream_raises_apierror_on_429():
    respx.post("http://test/agent/turn").mock(
        return_value=httpx.Response(429, json={"detail": "rate limit exceeded"}))
    with pytest.raises(api_client.ApiError) as ei:
        async for _ in api_client.run_agent_stream({"goal": "x", "model": "m"}):
            pass
    assert ei.value.status == 429
    assert "rate limit" in ei.value.detail


@respx.mock
async def test_health_pings_healthz():
    route = respx.get("http://test/healthz").mock(
        return_value=httpx.Response(200, json={"status": "ok"}))
    out = await api_client.health()
    assert out == {"status": "ok"}
    assert route.called


@respx.mock
async def test_bigquery_status_gets_status():
    route = respx.get("http://test/bigquery/status").mock(
        return_value=httpx.Response(200, json={"connected": True, "project": "p",
                                               "auth_expired": False, "error": None}))
    out = await api_client.bigquery_status()
    assert out["connected"] is True
    assert route.called


@respx.mock
async def test_bigquery_reconnect_posts():
    route = respx.post("http://test/bigquery/reconnect").mock(
        return_value=httpx.Response(200, json={"started": True}))
    out = await api_client.bigquery_reconnect()
    assert out["started"] is True
    assert route.called


@respx.mock
async def test_save_conversation_sends_tools():
    route = respx.put("http://test/projects/p1/conversations/c1").mock(
        return_value=httpx.Response(200, json={"id": "c1"}))
    tools = {"mcp": ["playwright"], "bigquery": False}
    await api_client.save_conversation("p1", "c1", [{"role": "user", "content": "x"}],
                                       title="T", tools=tools)
    body = json.loads(route.calls.last.request.content)
    assert body["tools"] == tools
