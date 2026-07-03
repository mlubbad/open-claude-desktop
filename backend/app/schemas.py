from __future__ import annotations

from pydantic import BaseModel


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    token: str


class Message(BaseModel):
    role: str
    content: str
    kind: str = "user"


class AgentOptions(BaseModel):
    web_search: bool = False
    research: bool = False
    web_fetch: bool = False
    code_exec: bool = False
    bash: bool = False
    text_editor: bool = False
    memory: bool = False
    artifacts: bool = True


class AgentTurnRequest(BaseModel):
    project_id: str | None = None
    goal: str
    history: list[Message] = []
    model: str
    provider: str | None = None      # explicit provider; else inferred from model/default
    effort: str = "High"
    permission_mode: str | None = None   # auto | ask | strict (HITL); None -> server default
    options: AgentOptions = AgentOptions()
    enabled_plugins: list[str] = []
    enabled_connectors: list[str] = []
    enabled_mcp: list[str] = []


class PermissionReply(BaseModel):
    tool_call_id: str
    decision: str                    # "approve" | "decline"


class ProjectCreate(BaseModel):
    name: str


class TextBody(BaseModel):       # instructions / memory
    content: str


class AllowlistBody(BaseModel):
    tables: list[str]


class ConversationCreate(BaseModel):
    first_message: str


class ConversationSave(BaseModel):
    messages: list[Message]
    title: str | None = None


class ConversationPatch(BaseModel):
    title: str | None = None
    pinned: bool | None = None


class MoveBody(BaseModel):
    dst_project_id: str


class SettingsBody(BaseModel):
    model: str | None = None
    provider: str | None = None
    effort: str | None = None
    theme: str | None = None
    profile: dict | None = None


class TitleRequest(BaseModel):
    first_message: str


class SqlExecuteRequest(BaseModel):
    sql: str
    project: str | None = None


class GithubImportRequest(BaseModel):
    repo_url: str
    project_id: str
