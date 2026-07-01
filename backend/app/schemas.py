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


class AgentTurnRequest(BaseModel):
    project_id: str | None = None
    goal: str
    history: list[Message] = []
    model: str
    effort: str = "High"
    options: AgentOptions = AgentOptions()
    enabled_plugins: list[str] = []
    enabled_connectors: list[str] = []
    enabled_mcp: list[str] = []


class ProjectCreate(BaseModel):
    name: str


class TextBody(BaseModel):       # instructions / memory
    content: str


class AllowlistBody(BaseModel):
    tables: list[str]


class ConversationCreate(BaseModel):
    first_message: str


class ConversationSave(BaseModel):
    # NOT list[Message]: the frontend persists its full rich transcript here,
    # including tool/table/sources entries with no `content` field (id/name/
    # icon/status/summary/error, columns/rows, items, ...). Conversation.transcript
    # is untyped JSON storage with no shape requirement, so this passes through
    # as-is -- matching what GET already returns and what the frontend already
    # round-trips via _normalize_messages() on load.
    messages: list[dict]
    title: str | None = None
    tools: dict | None = None


class ConversationPatch(BaseModel):
    title: str | None = None
    pinned: bool | None = None


class MoveBody(BaseModel):
    dst_project_id: str


class SettingsBody(BaseModel):
    model: str | None = None
    effort: str | None = None
    theme: str | None = None


class TitleRequest(BaseModel):
    first_message: str


class SqlExecuteRequest(BaseModel):
    sql: str
    project: str | None = None


class GithubImportRequest(BaseModel):
    repo_url: str
    project_id: str
