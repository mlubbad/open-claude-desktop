from __future__ import annotations

from pydantic import BaseModel, field_validator


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
    subagents: bool = False


# Image attachments: bounded so one request can't blow the backend or the provider.
MAX_IMAGES = 6
MAX_IMAGE_CHARS = 8_000_000  # ~6 MB of base64 per image


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
    # data-URI images attached to THIS message (vision input). History stays text.
    images: list[str] = []
    # Response style: "normal"|"concise"|"explanatory"|"formal", or custom
    # instruction text (bounded). Empty/None = no style section.
    style: str | None = None

    @field_validator("style")
    @classmethod
    def _bound_style(cls, v: str | None) -> str | None:
        if v and len(v) > 2000:
            raise ValueError("style too long")
        return v

    @field_validator("permission_mode")
    @classmethod
    def _bound_permission_mode(cls, v: str | None) -> str | None:
        # None → server default. A recognized mode passes through (case-normalized); any
        # unrecognized string coerces to "strict" so a typo/injected value fails closed
        # rather than dropping to the autonomous "auto" path.
        if v is None:
            return None
        m = str(v).strip().lower()
        return m if m in {"strict", "ask", "auto"} else "strict"

    @field_validator("images")
    @classmethod
    def _bound_images(cls, v: list[str]) -> list[str]:
        if len(v) > MAX_IMAGES:
            raise ValueError(f"at most {MAX_IMAGES} images per message")
        for u in v:
            if not u.startswith("data:image/"):
                raise ValueError("images must be data:image/* URIs")
            if len(u) > MAX_IMAGE_CHARS:
                raise ValueError("image too large")
        return v


class PermissionReply(BaseModel):
    tool_call_id: str
    decision: str                    # "approve" | "decline"


class ProjectCreate(BaseModel):
    name: str
    description: str = ""


class ProjectPatch(BaseModel):
    name: str | None = None
    description: str | None = None
    pinned: bool | None = None
    archived: bool | None = None


class TextBody(BaseModel):       # instructions / memory
    content: str


class AllowlistBody(BaseModel):
    tables: list[str]


class ConversationCreate(BaseModel):
    first_message: str


class ConversationSave(BaseModel):
    messages: list[Message]
    title: str | None = None
    # Optimistic concurrency: the version the client last saw. When present, the save is
    # rejected (409) if the stored row has moved past it. Omit to force last-write-wins.
    version: int | None = None


class ConversationPatch(BaseModel):
    title: str | None = None
    pinned: bool | None = None


class MoveBody(BaseModel):
    dst_project_id: str


class BranchBody(BaseModel):
    at_index: int  # message index to fork the conversation at (0-based, inclusive)


class SettingsBody(BaseModel):
    model: str | None = None
    provider: str | None = None
    effort: str | None = None
    theme: str | None = None
    profile: dict | None = None
    search_provider: str | None = None
    searxng_url: str | None = None
    code_execution: str | None = None   # auto | docker | local | off
    permission_mode: str | None = None  # strict | ask | auto (HITL autonomy)
    memory_search: bool | None = None   # agent may search past chats mid-turn
    autonomy_paused: bool | None = None  # global kill-switch for unattended runs
    visible_models: dict | None = None  # {provider_id: [model, ...]} shown in the picker
    custom_models: dict | None = None   # {provider_id: [model, ...]} user-added model names
    hidden_models: dict | None = None   # {provider_id: [model, ...]} catalog models the user removed
    # Opik observability (opt-in). The API key is NEVER accepted here — it goes to the
    # keychain via /observability/key. These are non-secret config only.
    opik_enabled: bool | None = None
    opik_mode: str | None = None         # local | cloud
    opik_url: str | None = None          # self-hosted base URL (local mode)
    opik_project: str | None = None
    opik_workspace: str | None = None    # Opik Cloud workspace (cloud mode)


class TitleRequest(BaseModel):
    first_message: str


class SqlExecuteRequest(BaseModel):
    sql: str
    project: str | None = None


class GithubImportRequest(BaseModel):
    repo_url: str
    project_id: str
