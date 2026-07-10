"""Agent-assisted connector authentication — host CLI login flows.

Some connectors authenticate by running a CLI command that opens a browser for the
user's OAuth consent (BigQuery / Google Cloud via ADC, GitHub CLI, AWS SSO). This
module lets the agent run one of a small, ALLOW-LISTED set of those commands on the
host — always behind the HITL approval gate — streams its output, surfaces the
consent URL so the app can open a browser, and reports success once the user finishes
signing in there. The only thing asked of the user is the browser consent.

Safety: the model never supplies the command or its arguments. It only names a flow,
which maps to a FIXED command here — so a prompt-injected model cannot turn this into
arbitrary command execution. The commands are login flows only (no data access), run
with the real environment (they need HOME / gcloud config / proxy) but with a kill-on-
timeout session, and the resulting credentials are written to the user's own local CLI
config exactly as if they had run the command themselves.
"""
from __future__ import annotations

import contextlib
import os
import re
import shutil
from pathlib import Path

from . import config

# id -> flow spec. `command` is fixed; `cli` is the binary that must be on PATH;
# `match` are keywords (in an error message / user hint) that select this flow.
FLOWS: dict[str, dict] = {
    "gcloud-adc": {
        "label": "Google Cloud — Application Default Credentials",
        "cli": "gcloud",
        "command": ["gcloud", "auth", "application-default", "login"],
        "hint": "BigQuery and other Google Cloud connectors (ADC).",
        "match": ("application-default", "application default", "adc", "bigquery",
                  "google cloud", "gcloud auth application"),
        "docs": "https://cloud.google.com/docs/authentication/application-default-credentials",
    },
    "gcloud-user": {
        "label": "Google Cloud — user account",
        "cli": "gcloud",
        "command": ["gcloud", "auth", "login"],
        "hint": "gcloud CLI user login.",
        "match": ("gcloud auth login", "gcloud user", "gcloud login"),
        "docs": "https://cloud.google.com/sdk/gcloud/reference/auth/login",
    },
    "github": {
        "label": "GitHub CLI",
        "cli": "gh",
        "command": ["gh", "auth", "login", "--web", "--git-protocol", "https"],
        "hint": "GitHub (gh) connectors.",
        "match": ("github", "gh auth", "gh cli"),
        "docs": "https://cli.github.com/manual/gh_auth_login",
    },
    "aws-sso": {
        "label": "AWS IAM Identity Center (SSO)",
        "cli": "aws",
        "command": ["aws", "sso", "login"],
        "hint": "AWS connectors using SSO.",
        "match": ("aws sso", "aws sso login", "identity center"),
        "docs": "https://docs.aws.amazon.com/cli/latest/userguide/sso-using-profile.html",
    },
}

# First https URL on a streamed line; auth URLs are picked preferentially (see below).
_URL_RE = re.compile(r"https://[^\s\"'<>）)]+")
_AUTH_URL_HINTS = ("accounts.google.com", "oauth", "authorize", "device", "sso",
                   "signin", "login", "verification")


def enabled() -> bool:
    return bool(config.AUTH_FLOWS_ENABLED)


def _available(spec: dict) -> bool:
    return shutil.which(spec["cli"]) is not None


def spawn_argv(command: list[str]) -> list[str] | None:
    """Resolve ``command[0]`` to an absolute path so the OS can launch it, and on
    Windows route a ``.cmd``/``.bat`` shim (e.g. ``gcloud.cmd``) through the command
    processor. Returns None when the CLI isn't on PATH.

    Why this exists: on Windows the gcloud/gh CLIs install as batch shims, and
    ``CreateProcess`` neither searches PATHEXT for a bare name nor executes a batch
    file directly — so spawning ``["gcloud", ...]`` raised ``WinError 2`` ("system
    cannot find the file specified") even though gcloud WAS installed. That is the
    exact failure the in-app `authenticate` tool hit; users had to fall back to a
    separate terminal. Resolving to the shim's full path and prefixing ``cmd /c``
    makes the in-app sign-in work on Windows too.
    """
    exe = shutil.which(command[0])
    if not exe:
        return None
    argv = [exe, *command[1:]]
    if os.name == "nt" and exe.lower().endswith((".cmd", ".bat")):
        return [os.environ.get("COMSPEC", "cmd.exe"), "/c", *argv]
    return argv


def refresh_dependent_connectors(flow_id: str) -> None:
    """After a successful sign-in, drop cached credentials/connections that were built
    from the OLD token so the next call picks up the fresh one — WITHOUT a restart.

    This is the fix for the "re-authenticate on every prompt" loop: ``gcloud`` writes a
    fresh ADC token to disk, but the connector processes cached the stale token in
    memory at startup and never re-read it, so every subsequent call kept reporting
    "Reauthentication is needed." We proactively invalidate those caches on success.
    """
    # Native BigQuery client (built from ADC) — rebuild lazily on the next query.
    if flow_id in ("gcloud-adc", "gcloud-user"):
        with contextlib.suppress(Exception):
            from . import bigquery
            bigquery.reset_bq_client()
    # Any MCP connector that read credentials at startup (e.g. a BigQuery MCP server
    # using ADC) — close its live session so the next tool call respawns the process
    # with the refreshed credentials.
    with contextlib.suppress(Exception):
        from . import mcp_registry
        mcp_registry.registry.drop_all()


def list_flows() -> list[dict]:
    """The known login flows, each flagged whether its CLI is installed on this host."""
    return [
        {"id": fid, "label": s["label"], "cli": s["cli"], "hint": s["hint"],
         "docs": s["docs"], "available": _available(s),
         "command": " ".join(s["command"])}
        for fid, s in FLOWS.items()
    ]


def match_flow(hint: str) -> str | None:
    """Resolve a free-text provider hint (a flow id, a CLI name, or an error message)
    to a flow id — e.g. "gcloud auth application-default login" or "bigquery" ->
    "gcloud-adc"."""
    h = (hint or "").strip().lower()
    if not h:
        return None
    if h in FLOWS:
        return h
    # Prefer the most specific keyword match (longest matched keyword wins).
    best: tuple[int, str] | None = None
    for fid, spec in FLOWS.items():
        for kw in spec["match"]:
            if kw in h and (best is None or len(kw) > best[0]):
                best = (len(kw), fid)
    if best:
        return best[1]
    # Fall back to a bare CLI-name mention.
    for fid, spec in FLOWS.items():
        if spec["cli"] in h.split():
            return fid
    return None


def _pick_url(text: str) -> str | None:
    urls = _URL_RE.findall(text)
    if not urls:
        return None
    for u in urls:
        if any(k in u.lower() for k in _AUTH_URL_HINTS):
            return u
    return urls[0]


def run_flow(flow_id: str, on_output=None, on_url=None) -> dict:
    """Run a login flow's fixed command on the host, streaming output. When a consent
    URL appears it is passed to ``on_url`` exactly once (so the app can open a browser).
    Blocks until the command finishes (the user completing sign-in in the browser) or
    the human-paced timeout elapses. Returns {ok, detail, url, returncode}."""
    if not enabled():
        return {"ok": False, "detail": "connector sign-in is disabled on this install"}
    spec = FLOWS.get(flow_id)
    if not spec:
        return {"ok": False, "detail": f"unknown auth flow '{flow_id}'"}
    # Resolve the CLI to a spawn-ready argv (absolute path; cmd-wrapped on Windows).
    argv = spawn_argv(spec["command"])
    if argv is None:
        return {"ok": False, "detail": f"{spec['cli']} is not installed on this machine"}

    from . import integrations  # reuse the streaming subprocess + own-session isolation

    found: dict[str, str | None] = {"url": None}

    def _out(stream: str, text: str) -> None:
        if on_output:
            try:
                on_output(stream, text)
            except Exception:
                pass
        if found["url"] is None:
            url = _pick_url(text)
            if url:
                found["url"] = url
                if on_url:
                    try:
                        on_url(url)
                    except Exception:
                        pass

    # Inherit the real environment (gcloud/gh/aws need HOME, their config, and any
    # proxy), but never launch a browser from the server process — the app opens the
    # surfaced URL. A dedicated session lets a timeout kill the CLI, not the backend.
    env = dict(os.environ)
    env["BROWSER"] = "true"                 # CLIs that honor $BROWSER: no-op launcher
    env["CLOUDSDK_CORE_DISABLE_PROMPTS"] = "1"
    rc, out, err, timed_out = integrations._stream_subprocess(
        argv, cwd=Path.home(), env=env, on_output=_out,
        timeout=config.AUTH_FLOW_TIMEOUT_SEC,
        popen_extra=integrations._isolation_popen_extra(local=True))

    if timed_out:
        return {"ok": False, "url": found["url"], "returncode": -1,
                "detail": "sign-in timed out — the browser consent wasn't completed in time"}
    ok = rc == 0
    if ok:
        # The token on disk is fresh now; make every connector that cached the old one
        # reload it, so the very next tool call succeeds instead of looping on re-auth.
        refresh_dependent_connectors(flow_id)
    tail = (err or out or "").strip()[-400:]
    return {"ok": ok, "url": found["url"], "returncode": rc,
            "detail": (f"signed in with {spec['label']}" if ok
                       else f"sign-in failed (exit {rc}). {tail}")}
