from __future__ import annotations

from fastapi import APIRouter, Depends
from ocd_core import integrations, skills
from pydantic import BaseModel

from ..deps import current_user
from ..schemas import GithubImportRequest

router = APIRouter()


class ConnectorBody(BaseModel):
    name: str
    base_url: str
    header_key: str = ""
    header_value: str = ""


class McpBody(BaseModel):
    name: str
    command: str = ""                       # stdio: the command to launch
    args: list[str] = []
    url: str = ""                           # remote: Streamable-HTTP / SSE endpoint
    transport: str = ""                     # "http" (default for url) | "sse" | "stdio"
    env: dict[str, str] = {}                # per-server env (stdio) — merged safely
    headers: dict[str, str] = {}            # extra headers (remote)
    auth_token: str = ""                    # remote bearer token — stored in the keychain


@router.get("/plugins")
def list_plugins(user: str = Depends(current_user)) -> list[dict]:
    return integrations.list_plugins()


@router.get("/skills")
def list_skills(user: str = Depends(current_user)) -> list[dict]:
    return skills.list_skills()


@router.get("/connectors")
def list_connectors(user: str = Depends(current_user)) -> list[dict]:
    return integrations.list_connectors()


@router.post("/connectors")
def add_connector(body: ConnectorBody, user: str = Depends(current_user)) -> dict:
    return integrations.add_connector(body.name, body.base_url,
                                      body.header_key, body.header_value)


@router.delete("/connectors/{cid}")
def remove_connector(cid: str, user: str = Depends(current_user)) -> dict:
    integrations.remove_connector(cid)
    return {"ok": True}


@router.post("/connectors/{cid}/test")
def test_connector(cid: str, user: str = Depends(current_user)) -> dict:
    return {"result": integrations.test_connector(cid)}


@router.get("/mcp-servers")
def list_mcp(user: str = Depends(current_user)) -> list[dict]:
    return integrations.list_mcp_servers()


@router.post("/mcp-servers")
def add_mcp(body: McpBody, user: str = Depends(current_user)) -> dict:
    return integrations.add_mcp_server(
        body.name, body.command, body.args, url=body.url, transport=body.transport,
        env=body.env, headers=body.headers, auth_token=body.auth_token)


@router.delete("/mcp-servers/{sid}")
def remove_mcp(sid: str, user: str = Depends(current_user)) -> dict:
    integrations.remove_mcp_server(sid)
    return {"ok": True}


@router.get("/mcp-servers/{sid}/tools")
def mcp_tools(sid: str, user: str = Depends(current_user)) -> dict:
    return {"tools": integrations.mcp_tools([sid])}


@router.post("/mcp-servers/demo")
def add_demo_mcp(user: str = Depends(current_user)) -> dict:
    return integrations.add_demo_mcp_server()


@router.post("/connectors/github")
def import_github(body: GithubImportRequest, user: str = Depends(current_user)) -> dict:
    count, message = integrations.import_github_repo(body.repo_url, body.project_id)
    return {"chunks": count, "message": message}
