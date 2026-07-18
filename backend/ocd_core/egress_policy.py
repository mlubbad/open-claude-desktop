"""First-contact domain approval for the agent's ``web_fetch`` tool.

``web_fetch`` is the one agent tool whose destination is an arbitrary,
model-chosen URL, so it is the exfiltration path an injected prompt would use.
The agent loop gates the FIRST reach to a new hostname on user approval (reusing
the existing HITL ``approval_required`` / ``permissions.registry`` flow) and
remembers approvals PER PROJECT. Search / MCP / connectors go to fixed or
user-configured hosts, so they are deliberately NOT gated -- ``outbound_host``
returns ``None`` for them, which is the single place that defines the gated set.

Known limitation (tracked follow-up): approval covers the **initial** host only.
``web_fetch`` follows redirects, and a redirect to an unapproved host is still
re-checked for SSRF (``assert_public_url`` per hop) but NOT re-gated for domain
approval -- so an approved host carrying an open redirect can hand the request
to a host the user never approved. Closing this needs ``web_fetch`` to re-gate
each redirect hop against this registry (thread the project's approved set in
and refuse an unapproved cross-host hop). Until then, the gate is a first-hop
control, not a full egress allowlist.
"""
from __future__ import annotations

from urllib.parse import urlsplit

# Tools whose destination is agent-controlled and therefore domain-gated. Only
# web_fetch today; a set so adding one later is a one-line change.
_GATED_TOOLS = {"web_fetch"}

# Bucket for turns with no active project. The NUL prefix can't collide with a
# real project id (which is always a non-empty user/db string).
_NO_PROJECT = "\x00__no_project__"


def outbound_host(tool_name: str, args: dict | None) -> str | None:
    """The hostname a gated tool call would contact, or ``None`` when this call
    isn't domain-gated (not a gated tool, or no parseable host in its args)."""
    if tool_name not in _GATED_TOOLS or not isinstance(args, dict):
        return None
    url = (args.get("url") or "").strip()
    if not url:
        return None
    try:
        host = urlsplit(url).hostname
    except ValueError:
        return None
    if not host:
        return None
    return host.lower().rstrip(".")


class EgressApprovalRegistry:
    """Which hostnames the user has approved, scoped per project.

    In-memory only (single-user desktop; mirrors ``permissions.registry``). Not
    persisted across restarts yet -- ``ApprovalRecord`` persistence is a later
    add. A ``None`` project key maps to one stable shared bucket, isolated from
    every concrete project id.
    """

    def __init__(self) -> None:
        self._approved: dict[str, set[str]] = {}

    @staticmethod
    def _key(project_key: str | None) -> str:
        return _NO_PROJECT if project_key is None else project_key

    def is_approved(self, project_key: str | None, host: str) -> bool:
        return host in self._approved.get(self._key(project_key), ())

    def approve(self, project_key: str | None, host: str) -> None:
        self._approved.setdefault(self._key(project_key), set()).add(host)

    def reset(self) -> None:
        self._approved.clear()


registry = EgressApprovalRegistry()
