from __future__ import annotations

import json
import tempfile
from pathlib import Path

from fastapi import APIRouter, Body, Depends, File, Form, HTTPException, UploadFile
from ocd_core import auth_flows, connector_directory, integrations, marketplace, skills
from ocd_core.integrations import McpbError
from pydantic import BaseModel

from ..deps import current_user
from ..schemas import GithubImportRequest

router = APIRouter()


class PluginName(BaseModel):
    name: str


class SourceBody(BaseModel):
    url: str
    ref: str = ""
    name: str = ""


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


@router.get("/marketplace")
def marketplace_catalog(user: str = Depends(current_user)) -> list[dict]:
    """Browse the plugin catalog — bundled plugins plus any synced repository sources
    (each flagged `installed`, with its `origin`)."""
    return marketplace.catalog()


@router.get("/marketplace/sources")
def marketplace_sources(user: str = Depends(current_user)) -> dict:
    """The synced repository sources plus whether adding remote ones is allowed."""
    return {"allow_remote": marketplace.remote_allowed(), "sources": marketplace.list_sources()}


@router.post("/marketplace/sources")
def marketplace_add_source(body: SourceBody, user: str = Depends(current_user)) -> dict:
    """Sync a plugin marketplace from a git URL. Runs third-party plugin code on install,
    so it is gated on MARKETPLACE_ALLOW_REMOTE and is an explicit, warned user action."""
    if not marketplace.remote_allowed():
        raise HTTPException(status_code=403, detail="remote marketplaces are disabled")
    res = marketplace.add_source(body.url, body.ref, body.name)
    if not res.get("ok"):
        raise HTTPException(status_code=400, detail=res.get("detail", "could not add source"))
    return res


@router.delete("/marketplace/sources/{sid}")
def marketplace_remove_source(sid: str, user: str = Depends(current_user)) -> dict:
    res = marketplace.remove_source(sid)
    if not res.get("ok"):
        raise HTTPException(status_code=400, detail=res.get("detail", "could not remove source"))
    return res


@router.post("/marketplace/install")
def marketplace_install(body: PluginName, user: str = Depends(current_user)) -> dict:
    res = marketplace.install(body.name)
    if not res.get("ok"):
        raise HTTPException(status_code=400, detail=res.get("detail", "install failed"))
    return res


@router.post("/marketplace/uninstall")
def marketplace_uninstall(body: PluginName, user: str = Depends(current_user)) -> dict:
    res = marketplace.uninstall(body.name)
    if not res.get("ok"):
        raise HTTPException(status_code=400, detail=res.get("detail", "uninstall failed"))
    return res


class SkillImport(BaseModel):
    filename: str = "skill.md"
    content: str


@router.get("/skills")
def list_skills(user: str = Depends(current_user)) -> list[dict]:
    return skills.list_skills()


@router.post("/skills")
def import_skill(body: SkillImport, user: str = Depends(current_user)) -> dict:
    """Import a skill from an uploaded markdown file."""
    res = skills.import_skill(body.filename, body.content)
    if not res.get("ok"):
        raise HTTPException(status_code=400, detail=res.get("detail", "import failed"))
    return res


@router.post("/skills/import-zip")
def import_skills_zip(file: UploadFile = File(...), user: str = Depends(current_user)) -> dict:
    """Import skills from an uploaded .zip of a skill folder (canonical SKILL.md layout).
    The archive is extracted server-side and walked like a synced repository."""
    path = _spool_upload(file)
    try:
        res = skills.import_skills_from_zip(path, file.filename or "")
        if not res.get("ok"):
            raise HTTPException(status_code=400, detail=res.get("detail", "import failed"))
        return res
    finally:
        path.unlink(missing_ok=True)


@router.post("/skills/from-repo")
def import_skills_from_repo(body: SourceBody, user: str = Depends(current_user)) -> dict:
    """Sync skills from a git repository (one-shot copy of its markdown skill files)."""
    if not marketplace.remote_allowed():
        raise HTTPException(status_code=403, detail="remote marketplaces are disabled")
    res = skills.import_skills_from_repo(body.url, body.ref)
    if not res.get("ok"):
        raise HTTPException(status_code=400, detail=res.get("detail", "could not sync"))
    return res


@router.delete("/skills/{name}")
def remove_skill(name: str, user: str = Depends(current_user)) -> dict:
    res = skills.remove_skill(name)
    if not res.get("ok"):
        raise HTTPException(status_code=400, detail=res.get("detail", "could not remove"))
    return res


@router.get("/auth-flows")
def list_auth_flows(user: str = Depends(current_user)) -> dict:
    """Login flows the agent can run to sign a connector in (with per-CLI availability).
    The actual sign-in runs through the agent's `authenticate` tool (HITL-gated)."""
    return {"enabled": auth_flows.enabled(), "flows": auth_flows.list_flows()}


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


class ToolEnabledBody(BaseModel):
    enabled: bool


@router.post("/mcp-servers/{sid}/tools/{tool_name}")
def set_mcp_tool(sid: str, tool_name: str, body: ToolEnabledBody,
                 user: str = Depends(current_user)) -> dict:
    """Enable/disable ONE tool within a connector (P1-12)."""
    server = integrations.set_mcp_tool_enabled(sid, tool_name, body.enabled)
    if server is None:
        raise HTTPException(404, "no such server")
    return server


@router.get("/connectors/directory")
def connectors_directory(user: str = Depends(current_user)) -> list[dict]:
    """Curated catalog of well-known open MCP servers ("browse connectors"). Static
    and offline; each entry prefills the add form — nothing runs without an explicit
    user add."""
    return connector_directory.list_directory()


@router.post("/mcp-servers")
def add_mcp(body: McpBody, user: str = Depends(current_user)) -> dict:
    return integrations.add_mcp_server(
        body.name, body.command, body.args, url=body.url, transport=body.transport,
        env=body.env, headers=body.headers, auth_token=body.auth_token)


@router.delete("/mcp-servers/{sid}")
def remove_mcp(sid: str, user: str = Depends(current_user)) -> dict:
    integrations.remove_mcp_server(sid)
    return {"ok": True}


@router.post("/mcp-servers/{sid}/refresh")
def refresh_mcp(sid: str, user: str = Depends(current_user)) -> dict:
    """Re-connect a server from scratch — the error card's Retry button. Recovers a
    first-run timeout (package/image now cached) or a fixed PATH without re-adding."""
    res = integrations.refresh_mcp_server(sid)
    if not res:
        raise HTTPException(status_code=404, detail="unknown MCP server")
    return res


@router.get("/mcp-servers/{sid}/update")
def check_mcp_update(sid: str, user: str = Depends(current_user)) -> dict:
    """Check GitHub Releases for a newer bundle of an installed .mcpb extension
    (P1-13). `latest` is null when already current."""
    try:
        return integrations.check_mcpb_update(sid)
    except McpbError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


class McpUpdateBody(BaseModel):
    # Extra user_config values for the NEW manifest (only needed when the update
    # added a required field; install-time answers come from the keychain).
    values: dict[str, str] = {}


@router.post("/mcp-servers/{sid}/update")
def apply_mcp_update(sid: str, body: McpUpdateBody | None = None,
                     user: str = Depends(current_user)) -> dict:
    """Download the newest release bundle and reinstall the extension in place."""
    try:
        return integrations.update_mcpb(sid, body.values if body else {})
    except McpbError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


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


@router.get("/mcp-servers/{sid}/oauth")
def mcp_oauth_status(sid: str, user: str = Depends(current_user)) -> dict:
    """OAuth authorization status for a connector (authorized?, scope, has_refresh)."""
    return integrations.mcp_oauth_status(sid)


class OAuthServerBody(BaseModel):
    name: str
    url: str
    transport: str = "http"


@router.post("/mcp-servers/oauth")
def add_oauth_mcp(body: OAuthServerBody, user: str = Depends(current_user)) -> dict:
    """Register a remote MCP server that authenticates via OAuth 2.1 (authorize later)."""
    return integrations.add_oauth_mcp_server(body.name, body.url, body.transport)


@router.post("/mcp-servers/{sid}/authorize")
def authorize_mcp(sid: str, user: str = Depends(current_user)) -> dict:
    """Run the interactive OAuth 2.1 authorize for a connector (opens the browser)."""
    try:
        return integrations.authorize_mcp_oauth(sid)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


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
