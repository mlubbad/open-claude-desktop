from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_projects_card_view():
    fake_projects = [{"id": "p1", "name": "P1", "created_at": "2026-01-01"}]
    fake_card = {"id": "p1", "name": "P1", "updated": "Jan 1", "desc": "d", "href": "/project/p1"}
    with patch("app.routes.projects.projects.list_projects", return_value=fake_projects), \
         patch("app.routes.projects.projects.project_card_view", return_value=fake_card):
        r = client.get("/projects", params={"view": "card"})
    assert r.status_code == 200
    assert r.json() == [fake_card]


def test_projects_card_view_newest_first():
    rows = [
        {"id": "old", "name": "Old", "created_at": "2026-01-01"},
        {"id": "new", "name": "New", "created_at": "2026-06-01"},
        {"id": "mid", "name": "Mid", "created_at": "2026-03-01"},
    ]
    # Mock list_projects for the ordering input; patch project_card_view with a
    # hermetic echo (the real one reads project metadata) so we test ordering only.
    with patch("app.routes.projects.projects.list_projects", return_value=rows), \
         patch("app.routes.projects.projects.project_card_view",
               side_effect=lambda p: {"id": p["id"], "created_at": p["created_at"]}):
        r = client.get("/projects", params={"view": "card"})
    ids = [c["id"] for c in r.json()]
    assert ids == ["new", "mid", "old"]


def test_projects_plain_view_unchanged():
    with patch("app.routes.projects.projects.list_projects", return_value=[{"id": "p1"}]):
        r = client.get("/projects")
    assert r.json() == [{"id": "p1"}]


def test_conversation_title():
    with patch("app.routes.conversations.conversations.generate_conversation_title",
               return_value="Quarterly Revenue") as m:
        r = client.post("/conversations/title", json={"first_message": "how much did we make"})
    assert r.json() == {"title": "Quarterly Revenue"}
    m.assert_called_once_with("how much did we make")


def test_list_all_files():
    rows = [{"name": "a.csv", "project_id": "p1", "project_name": "P1"}]
    with patch("app.routes.knowledge.knowledge.list_all_files", return_value=rows) as m:
        r = client.get("/files", params={"limit": 50})
    assert r.json() == rows
    m.assert_called_once_with(50)


def test_sql_execute():
    result = {"ok": True, "rows": [{"n": 1}], "columns": ["n"], "total_rows": 1,
              "bytes": 10, "agent_text": "[1 rows]"}
    with patch("app.routes.sql.bigquery.execute_sql", return_value=result) as m:
        r = client.post("/sql/execute", json={"sql": "SELECT 1", "project": "p1"})
    assert r.json() == result
    m.assert_called_once_with("SELECT 1", "p1")


def test_demo_mcp_route_removed():
    # The "AJ360 Demo" one-click registration route (POST /mcp-servers/demo) has
    # been removed. With the POST handler gone, that path only matches the generic
    # DELETE /mcp-servers/{sid} route, so a POST now yields 405 (Method Not Allowed)
    # rather than being served — either 404 or 405 confirms the endpoint is gone.
    assert client.post("/mcp-servers/demo").status_code in (404, 405)


def test_import_github_repo():
    with patch("app.routes.integrations.integrations.import_github_repo",
               return_value=(7, "")) as m:
        r = client.post("/connectors/github", json={"repo_url": "owner/repo", "project_id": "p1"})
    assert r.json() == {"chunks": 7, "message": ""}
    m.assert_called_once_with("owner/repo", "p1")
