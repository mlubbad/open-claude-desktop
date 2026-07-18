from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from ocd_core import auth, integrations, netguard, skills
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
    command: str
    args: list[str] = []


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
    # Registering a stdio MCP server spawns an arbitrary local command at discovery.
    # Refuse that when the backend is unauthenticated -- otherwise anyone who can
    # reach the port gets remote code execution -- unless the operator opts in.
    if not auth.auth_enabled() and not netguard.allow_unauthenticated():
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "MCP server registration is disabled while authentication is not "
            "configured. Configure auth, or set OCD_ALLOW_UNAUTHENTICATED=true "
            "for trusted local use.")
    return integrations.add_mcp_server(body.name, body.command, body.args)


@router.delete("/mcp-servers/{sid}")
def remove_mcp(sid: str, user: str = Depends(current_user)) -> dict:
    integrations.remove_mcp_server(sid)
    return {"ok": True}


@router.get("/mcp-servers/{sid}/tools")
def mcp_tools(sid: str, user: str = Depends(current_user)) -> dict:
    return {"tools": integrations.mcp_tools([sid])}


@router.post("/connectors/github")
def import_github(body: GithubImportRequest, user: str = Depends(current_user)) -> dict:
    count, message = integrations.import_github_repo(body.repo_url, body.project_id)
    return {"chunks": count, "message": message}
