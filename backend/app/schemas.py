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
