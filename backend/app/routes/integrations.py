from __future__ import annotations

import json
import tempfile
from pathlib import Path

from fastapi import APIRouter, Body, Depends, File, Form, HTTPException, UploadFile
from ocd_core import integrations, skills
from ocd_core.integrations import McpbError
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


@router.get("/mcp-servers/{sid}/resources")
def mcp_resources(sid: str, user: str = Depends(current_user)) -> dict:
    return {"resources": integrations.mcp_resources(sid)}


@router.get("/mcp-servers/{sid}/resources/read")
def mcp_read_resource(sid: str, uri: str, user: str = Depends(current_user)) -> dict:
    return {"content": integrations.mcp_read_resource(sid, uri)}


@router.get("/mcp-servers/{sid}/prompts")
def mcp_prompts(sid: str, user: str = Depends(current_user)) -> dict:
    return {"prompts": integrations.mcp_prompts(sid)}


@router.post("/mcp-servers/{sid}/prompts/{name}")
def mcp_get_prompt(sid: str, name: str, args: dict = Body(default={}),
                   user: str = Depends(current_user)) -> dict:
    return integrations.mcp_get_prompt(sid, name, args)


@router.post("/mcp-servers/demo")
def add_demo_mcp(user: str = Depends(current_user)) -> dict:
    return integrations.add_demo_mcp_server()


@router.get("/mcp-servers/{sid}/oauth")
def mcp_oauth_status(sid: str, user: str = Depends(current_user)) -> dict:
    """OAuth authorization status for a connector (authorized?, scope, has_refresh)."""
    return integrations.mcp_oauth_status(sid)


def _spool_upload(file: UploadFile) -> Path:
    """Persist an uploaded bundle to a temp file so the installer can open it as a
    real zip. Caller is responsible for unlinking it."""
    suffix = Path(file.filename or "bundle.mcpb").suffix or ".mcpb"
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    try:
        tmp.write(file.file.read())
    finally:
        tmp.close()
    return Path(tmp.name)


@router.post("/mcp-servers/inspect")
def inspect_mcpb(file: UploadFile = File(...), user: str = Depends(current_user)) -> dict:
    """Read a .mcpb/.dxt bundle's manifest (name, version, description, user_config)
    WITHOUT installing it — lets the UI collect required user_config up front."""
    path = _spool_upload(file)
    try:
        return integrations.mcpb_manifest_info(path)
    except McpbError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    finally:
        path.unlink(missing_ok=True)


@router.post("/mcp-servers/install")
def install_mcpb(file: UploadFile = File(...), user_config: str = Form("{}"),
                 user: str = Depends(current_user)) -> dict:
    """One-click install: unpack a .mcpb/.dxt bundle and register its MCP server.
    ``user_config`` is a JSON object of values for the manifest's user_config."""
    try:
        values = json.loads(user_config or "{}")
        if not isinstance(values, dict):
            raise ValueError("user_config must be a JSON object")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"bad user_config: {e}") from e
    path = _spool_upload(file)
    try:
        return integrations.install_mcpb(path, values)
    except McpbError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    finally:
        path.unlink(missing_ok=True)


@router.post("/connectors/github")
def import_github(body: GithubImportRequest, user: str = Depends(current_user)) -> dict:
    count, message = integrations.import_github_repo(body.repo_url, body.project_id)
    return {"chunks": count, "message": message}
