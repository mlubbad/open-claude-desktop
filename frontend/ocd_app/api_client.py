"""Typed async HTTP/SSE client for the OCD FastAPI backend.

The frontend's ONLY link to the backend. No ocd_core imports anywhere.
The agent turn preserves the backend's real event vocabulary end to end
(think_open/think_close/delta/answer_open/answer_to_think/tool/tool_result/
tool_error/table/sources/error) so state.py's renderer is reused verbatim.
"""
from __future__ import annotations

import json
import os
from collections.abc import AsyncIterator

import httpx
from httpx_sse import aconnect_sse

_BASE: str = os.environ.get("OCD_API_URL", "http://localhost:8000")
_TOKEN: str | None = None


class ApiError(Exception):
    def __init__(self, status: int, detail: str) -> None:
        super().__init__(f"{status}: {detail}")
        self.status = status
        self.detail = detail


def configure(base_url: str | None = None, token: str | None = ...) -> None:
    """Set the base URL and/or auth token. Pass token=None to clear it."""
    global _BASE, _TOKEN
    if base_url is not None:
        _BASE = base_url
    if token is not ...:
        _TOKEN = token


def _headers(extra: dict[str, str] | None = None) -> dict[str, str]:
    h = dict(extra or {})
    if _TOKEN:
        h["Authorization"] = f"Bearer {_TOKEN}"
    return h


async def _request(method: str, path: str, **kw) -> httpx.Response:
    async with httpx.AsyncClient(base_url=_BASE, timeout=60.0) as client:
        resp = await client.request(method, path, headers=_headers(kw.pop("headers", None)), **kw)
    if resp.status_code >= 400:
        detail = ""
        try:
            detail = resp.json().get("detail", "")
        except Exception:
            detail = resp.text
        raise ApiError(resp.status_code, detail)
    return resp


async def _get(path: str, **kw) -> object:
    return (await _request("GET", path, **kw)).json()


async def _post(path: str, json_body: object | None = None, **kw) -> object:
    return (await _request("POST", path, json=json_body, **kw)).json()


async def _put(path: str, json_body: object) -> object:
    return (await _request("PUT", path, json=json_body)).json()


async def _patch(path: str, json_body: object) -> object:
    return (await _request("PATCH", path, json=json_body)).json()


async def _delete(path: str) -> object:
    return (await _request("DELETE", path)).json()


# ----------------------------- auth ----------------------------- #
async def login(username: str, password: str) -> str:
    data = await _post("/auth/login", {"username": username, "password": password})
    token = data["token"]
    configure(token=token)
    return token


async def health() -> dict:
    return await _get("/healthz")  # type: ignore[return-value]


# --------------------------- bigquery --------------------------- #
async def bigquery_status() -> dict:
    return await _get("/bigquery/status")  # type: ignore[return-value]


async def bigquery_reconnect() -> dict:
    return await _post("/bigquery/reconnect")  # type: ignore[return-value]


# --------------------------- projects --------------------------- #
async def list_projects() -> list[dict]:
    return await _get("/projects")  # type: ignore[return-value]


async def list_project_cards() -> list[dict]:
    return await _get("/projects", params={"view": "card"})  # type: ignore[return-value]


async def create_project(name: str) -> dict:
    return await _post("/projects", {"name": name})  # type: ignore[return-value]


async def get_project(pid: str) -> dict:
    return await _get(f"/projects/{pid}")  # type: ignore[return-value]


async def delete_project(pid: str) -> bool:
    return bool((await _delete(f"/projects/{pid}"))["ok"])


async def get_project_instructions(pid: str) -> str:
    return (await _get(f"/projects/{pid}/instructions"))["content"]


async def save_project_instructions(pid: str, content: str) -> None:
    await _put(f"/projects/{pid}/instructions", {"content": content})


async def get_project_memory(pid: str) -> tuple[str, str]:
    d = await _get(f"/projects/{pid}/memory")
    return d["content"], d["updated_rel"]


async def save_project_memory(pid: str, content: str) -> None:
    await _put(f"/projects/{pid}/memory", {"content": content})


async def project_capacity(pid: str) -> dict:
    return await _get(f"/projects/{pid}/capacity")  # type: ignore[return-value]


# ------------------------ conversations ------------------------- #
async def list_conversations(pid: str) -> list[dict]:
    return await _get(f"/projects/{pid}/conversations")  # type: ignore[return-value]


async def list_all_conversations(limit: int = 200) -> list[dict]:
    return await _get("/conversations", params={"limit": limit})  # type: ignore[return-value]


async def create_conversation(pid: str, first_message: str) -> dict:
    return await _post(f"/projects/{pid}/conversations", {"first_message": first_message})  # type: ignore[return-value]


async def get_conversation(pid: str, cid: str) -> dict:
    return await _get(f"/projects/{pid}/conversations/{cid}")  # type: ignore[return-value]


async def save_conversation(pid: str, cid: str, messages: list[dict],
                            title: str | None = None, tools: dict | None = None) -> dict:
    return await _put(f"/projects/{pid}/conversations/{cid}",
                      {"messages": messages, "title": title, "tools": tools})  # type: ignore[return-value]


async def set_conversation_title(pid: str, cid: str, title: str) -> None:
    await _patch(f"/projects/{pid}/conversations/{cid}", {"title": title})


async def set_conversation_pinned(pid: str, cid: str, pinned: bool) -> None:
    await _patch(f"/projects/{pid}/conversations/{cid}", {"pinned": pinned})


async def move_conversation(pid: str, cid: str, dst_project_id: str) -> bool:
    return bool((await _post(f"/projects/{pid}/conversations/{cid}/move",
                             {"dst_project_id": dst_project_id}))["ok"])


async def delete_conversation(pid: str, cid: str) -> None:
    await _delete(f"/projects/{pid}/conversations/{cid}")


async def generate_conversation_title(first_message: str) -> str:
    return (await _post("/conversations/title", {"first_message": first_message}))["title"]


# --------------------------- knowledge -------------------------- #
async def list_project_files(pid: str) -> list[dict]:
    return await _get(f"/projects/{pid}/files")  # type: ignore[return-value]


async def list_all_files(limit: int = 500) -> list[dict]:
    return await _get("/files", params={"limit": limit})  # type: ignore[return-value]


async def upload_file(pid: str, filename: str, data: bytes) -> dict:
    files = {"file": (filename, data)}
    return (await _request("POST", f"/projects/{pid}/files", files=files)).json()


# ----------------------------- sql ------------------------------ #
async def execute_sql(sql: str, project: str | None = None) -> dict:
    return await _post("/sql/execute", {"sql": sql, "project": project})  # type: ignore[return-value]


# ---------------------------- settings -------------------------- #
async def get_settings() -> dict:
    return await _get("/settings")  # type: ignore[return-value]


async def save_settings(patch: dict) -> dict:
    return await _put("/settings", patch)  # type: ignore[return-value]


# -------------------------- integrations ------------------------ #
async def list_plugins() -> list[dict]:
    return await _get("/plugins")  # type: ignore[return-value]


async def list_skills() -> list[dict]:
    return await _get("/skills")  # type: ignore[return-value]


async def list_connectors() -> list[dict]:
    return await _get("/connectors")  # type: ignore[return-value]


async def add_connector(name: str, base_url: str, header_key: str = "", header_value: str = "") -> dict:
    return await _post("/connectors", {"name": name, "base_url": base_url,
                                       "header_key": header_key, "header_value": header_value})  # type: ignore[return-value]


async def remove_connector(cid: str) -> None:
    await _delete(f"/connectors/{cid}")


async def test_connector(cid: str) -> str:
    return (await _post(f"/connectors/{cid}/test"))["result"]


async def import_github_repo(repo_url: str, project_id: str) -> dict:
    return await _post("/connectors/github", {"repo_url": repo_url, "project_id": project_id})  # type: ignore[return-value]


async def list_mcp_servers() -> list[dict]:
    return await _get("/mcp-servers")  # type: ignore[return-value]


async def add_mcp_server(name: str, command: str, args: list[str]) -> dict:
    return await _post("/mcp-servers", {"name": name, "command": command, "args": args})  # type: ignore[return-value]


async def add_demo_mcp_server() -> dict:
    return await _post("/mcp-servers/demo")  # type: ignore[return-value]


async def remove_mcp_server(sid: str) -> None:
    await _delete(f"/mcp-servers/{sid}")


# ----------------------------- schema --------------------------- #
async def search_schema(q: str, project: str | None = None) -> str:
    return (await _get("/schema/search", params={"q": q, "project": project}))["result"]


# -------------------------- agent (SSE) ------------------------- #
async def run_agent_stream(req: dict) -> AsyncIterator[dict]:
    """Stream a turn. Yields the backend's event dicts unchanged; stops on `done`."""
    async with httpx.AsyncClient(base_url=_BASE, timeout=None) as client:
        async with aconnect_sse(client, "POST", "/agent/turn",
                                json=req, headers=_headers()) as es:
            if es.response.status_code >= 400:
                await es.response.aread()
                try:
                    detail = es.response.json().get("detail", "")
                except Exception:
                    detail = es.response.text
                raise ApiError(es.response.status_code, detail)
            async for sse in es.aiter_sse():
                ev = json.loads(sse.data)
                if ev.get("type") == "done":
                    return
                yield ev
