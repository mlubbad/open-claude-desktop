"""
Integrations domain layer — Skills, GitHub import, Connectors, Web search.

UI-agnostic. Everything here is plain sync Python (callers wrap blocking work in
asyncio.to_thread). Keeps the composer's "+" menu features out of core.py.
"""
from __future__ import annotations

import contextlib
import json
import os
import re
import shutil
import zipfile
from pathlib import Path

from . import bigquery, chroma, config, jsonstore, knowledge, llm, mcp_registry

SKILLS_DIR = Path(os.getenv("SKILLS_DIR", str(config.REPO_ROOT / "skills")))


# --------------------------------------------------------------------------- #
#  Skills  (skills/*.md with optional YAML-ish frontmatter)
#
#  Canonical implementation now lives in ocd_core.skills (merged with the copy
#  that used to live in root app.py). Re-exported here so the integrations
#  public API (list_skills/get_skill/matching_skill, plus the private alias
#  _split_frontmatter) is unchanged. ocd_core.skills defaults to
#  config.SKILLS_DIR, which resolves to the same skills/ dir as SKILLS_DIR above.
#  The returned dicts are a superset of the old ones (they additionally carry
#  file_triggers + references), which is backward-compatible for callers.
# --------------------------------------------------------------------------- #


# --------------------------------------------------------------------------- #
#  Plugins runtime — load plugins/*.py exposing TOOL (schema) + run(args)
# --------------------------------------------------------------------------- #
PLUGINS_DIR = Path(os.getenv("PLUGINS_DIR", str(config.REPO_ROOT / "plugins")))


# Loaded plugin modules are cached by (path, mtime). list_plugins()/plugin_tools()
# run on EVERY agent turn, so without this every turn re-imported and re-EXECUTED
# each plugin file's top-level code (paying its imports + side effects each time).
# We re-exec only when a file's mtime changes; a plugin edit is picked up on save.
_PLUGIN_CACHE: dict[Path, tuple[float, object]] = {}


def _load_plugin_module(path: Path):
    import importlib.util
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return None
    cached = _PLUGIN_CACHE.get(path)
    if cached is not None and cached[0] == mtime:
        return cached[1]
    try:
        spec = importlib.util.spec_from_file_location(
            f"aj360_plugin_{path.stem}", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)  # type: ignore[union-attr]
    except Exception:
        return None
    _PLUGIN_CACHE[path] = (mtime, mod)
    return mod


def list_plugins() -> list[dict]:
    out = []
    if not PLUGINS_DIR.is_dir():
        return out
    for f in sorted(PLUGINS_DIR.glob("*.py")):
        if f.name.startswith("_"):
            continue
        mod = _load_plugin_module(f)
        if mod and hasattr(mod, "TOOL") and hasattr(mod, "run"):
            out.append({
                "name": getattr(mod, "NAME", f.stem),
                "description": getattr(mod, "DESCRIPTION", "")[:120],
                "tool": mod.TOOL,
            })
    return out


def plugin_tools(enabled: list[str]) -> list[dict]:
    return [p["tool"] for p in list_plugins() if p["name"] in enabled]


def run_plugin(name: str, args: dict) -> str:
    for f in PLUGINS_DIR.glob("*.py"):
        if f.name.startswith("_"):
            continue
        mod = _load_plugin_module(f)
        if mod and getattr(mod, "NAME", f.stem) == name and hasattr(mod, "run"):
            try:
                return str(mod.run(args))
            except Exception as e:
                return f"Plugin '{name}' error: {e}"
    return f"Plugin '{name}' not found."


# --------------------------------------------------------------------------- #
#  Connectors — live status of built-in sources + managed REST connectors
#  User connectors persist to connectors.json and can be exposed as agent tools.
# --------------------------------------------------------------------------- #
CONNECTORS_FILE = config.REPO_ROOT / "connectors.json"


def _load_user_connectors() -> list[dict]:
    return jsonstore.load_json(CONNECTORS_FILE, [])


def _save_user_connectors(items: list[dict]):
    jsonstore.save_json(CONNECTORS_FILE, items)


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", (text or "").lower()).strip("_") or "rest"


def _connector_secret_key(cid: str) -> str:
    return f"connector:{cid}:auth"


def _connector_header_value(u: dict) -> str:
    """Resolve a connector's auth header value.

    Prefers the secret store (C3). Falls back to any legacy inline ``header_value``
    for back-compat with connectors saved before secrets were externalized.
    """
    if u.get("has_secret"):
        from . import secrets
        return secrets.get_secret_store().get(_connector_secret_key(u["id"])) or ""
    return u.get("header_value", "")


def add_connector(name: str, base_url: str, header_key: str = "",
                  header_value: str = "") -> dict:
    items = _load_user_connectors()
    cid = _slug(name)
    base = cid
    i = 2
    while any(it["id"] == cid for it in items):
        cid = f"{base}_{i}"
        i += 1
    item = {"id": cid, "name": name.strip() or cid, "type": "rest",
            "base_url": base_url.strip().rstrip("/"),
            "header_key": header_key.strip(), "has_secret": False}
    # C3: the secret value goes to the OS keychain / encrypted store, never to the
    # git-ignored-but-plaintext connectors.json.
    secret = (header_value or "").strip()
    if secret:
        from . import secrets
        secrets.get_secret_store().set(_connector_secret_key(cid), secret)
        item["has_secret"] = True
    items.append(item)
    _save_user_connectors(items)
    return item


def remove_connector(cid: str):
    for it in _load_user_connectors():
        if it["id"] == cid and it.get("has_secret"):
            from . import secrets
            secrets.get_secret_store().delete(_connector_secret_key(cid))
    _save_user_connectors([i for i in _load_user_connectors() if i["id"] != cid])


def _http_get(url: str, headers: dict, timeout: int = 15):
    import httpx
    return httpx.get(url, headers=headers, timeout=timeout, follow_redirects=True)


class ConnectorBlocked(Exception):
    """Raised when a connector URL targets a blocked host or unsupported scheme."""


def _safe_outbound_get(url: str, headers: dict, auth_header: str = "",
                       timeout: int = 15, max_redirects: int = 4):
    """SSRF-guarded GET for user-configured connectors (review finding H2).

    Unlike ``_http_get`` this: (1) rejects non-http(s) schemes and private/internal
    hosts via ``_blocked_host`` BEFORE connecting, (2) follows redirects MANUALLY so
    each hop is re-validated against ``_blocked_host`` (closing the redirect-to-
    internal SSRF), and (3) DROPS the connector's custom auth header on any
    cross-origin redirect so a hostile endpoint can't harvest the user's API key by
    bouncing the request elsewhere.
    """
    from urllib.parse import urljoin, urlparse

    import httpx
    cur = (url or "").strip()
    hdrs = dict(headers)
    with httpx.Client(timeout=timeout, follow_redirects=False) as client:
        for _ in range(max_redirects + 1):
            p = urlparse(cur)
            if p.scheme not in ("http", "https") or not p.netloc:
                raise ConnectorBlocked("unsupported URL scheme (http/https only)")
            if _blocked_host(p.hostname or ""):
                raise ConnectorBlocked("target host is private/internal and blocked")
            r = client.get(cur, headers=hdrs)
            if r.status_code in (301, 302, 303, 307, 308) and r.headers.get("location"):
                nxt = urljoin(cur, r.headers["location"])
                if auth_header and urlparse(nxt).hostname != (p.hostname or ""):
                    hdrs.pop(auth_header, None)  # never leak the key cross-origin
                cur = nxt
                continue
            return r
    raise ConnectorBlocked("too many redirects")


def test_connector(cid: str) -> str:
    u = next((x for x in _load_user_connectors() if x["id"] == cid), None)
    if not u:
        return "Connector not found."
    headers = {"User-Agent": _UA}
    if u.get("header_key"):
        headers[u["header_key"]] = _connector_header_value(u)
    try:
        r = _safe_outbound_get(u["base_url"], headers, auth_header=u.get("header_key", ""))
        return f"OK — HTTP {r.status_code} from {u['base_url']}"
    except ConnectorBlocked as e:
        return f"Blocked: {e}"
    except Exception as e:
        return f"Failed: {str(e)[:120]}"


def list_connectors() -> list[dict]:
    connectors = []
    # BigQuery is an OPT-IN builtin: only advertise (and only touch Google auth) when
    # it's actually configured. A general model-agnostic install must not surface a
    # permanent "BigQuery — error" connector or run gcloud auth on every listing.
    if config.BIGQUERY_ENABLED:
        try:
            bigquery.get_bq_client()
            connectors.append({"id": "bigquery", "name": "BigQuery", "type": "builtin",
                               "status": "connected", "detail": config.PROJECT_ID})
        except Exception as e:
            connectors.append({"id": "bigquery", "name": "BigQuery", "type": "builtin",
                               "status": "error", "detail": str(e)[:80]})
    try:
        chroma._get_chroma()
        connectors.append({"id": "chromadb", "name": "ChromaDB (KB)", "type": "builtin",
                           "status": "connected", "detail": "local vector store"})
    except Exception as e:
        connectors.append({"id": "chromadb", "name": "ChromaDB (KB)", "type": "builtin",
                           "status": "error", "detail": str(e)[:80]})
    connectors.append({"id": "web", "name": "Web search", "type": "builtin",
                       "status": "available", "detail": "DuckDuckGo (keyless)"})
    for u in _load_user_connectors():
        connectors.append({"id": u["id"], "name": u["name"], "type": "rest",
                           "status": "configured", "detail": u.get("base_url", "")})
    return connectors


def connectors_attention() -> int:
    return sum(1 for c in list_connectors() if c["status"] == "error")


# ---- Connectors as agent tools (enabled REST connectors) ---- #
def _connector_tool_name(cid: str) -> str:
    return f"rest_{cid}"


def connector_tools(enabled_ids: list[str]) -> list[dict]:
    tools = []
    for u in _load_user_connectors():
        if u["id"] not in enabled_ids:
            continue
        tools.append({"type": "function", "function": {
            "name": _connector_tool_name(u["id"]),
            "description": (f"Call the '{u['name']}' REST API (base {u['base_url']}). "
                            "Provide `path` appended to the base URL "
                            "(e.g. '/v1/items?limit=5'). Returns the raw response."),
            "parameters": {"type": "object", "properties": {
                "path": {"type": "string", "description": "Path/query after the base URL."}},
                "required": ["path"]}}})
    return tools


def call_connector(cid: str, path: str) -> str:
    u = next((x for x in _load_user_connectors() if x["id"] == cid), None)
    if not u:
        return f"Connector '{cid}' not found."
    path = path or ""
    if path and not path.startswith("/") and not path.startswith("?"):
        path = "/" + path
    url = u["base_url"] + path
    headers = {"User-Agent": _UA, "Accept": "application/json, text/*"}
    if u.get("header_key"):
        headers[u["header_key"]] = _connector_header_value(u)
    try:
        r = _safe_outbound_get(url, headers, auth_header=u.get("header_key", ""), timeout=20)
        return f"HTTP {r.status_code} {url}\n{r.text[:3000]}"
    except ConnectorBlocked as e:
        return f"Connector '{cid}' blocked: {e}"
    except Exception as e:
        return f"Connector '{cid}' request failed: {str(e)[:160]}"


# --------------------------------------------------------------------------- #
#  MCP (Model Context Protocol) connectors — a real, non-REST connector path.
#  The app acts as an MCP *client*: it spawns/connects to an MCP server, discovers
#  its tools via list_tools(), and surfaces them to the agent as `mcp_<sid>_<tool>`.
#  This mirrors how Claude Desktop connectors actually work (MCP, not a REST key).
#
#  Tool specs are discovered ONCE at registration and cached in mcp_servers.json,
#  so the per-turn tool assembly stays synchronous; live sessions are owned by
#  the single-spawn mcp_registry (ONE persistent ClientSession per server,
#  reused across calls, with per-call timeouts + clean shutdown).
# --------------------------------------------------------------------------- #
MCP_FILE = config.REPO_ROOT / "mcp_servers.json"
# One-click desktop-extension bundles (.mcpb / legacy .dxt) unpack here, one dir
# per installed extension. Kept out of the repo tree via .gitignore.
EXTENSIONS_DIR = config.REPO_ROOT / "extensions"


# mtime-keyed cache of the registry file's TEXT. call_mcp re-reads the registry on
# EVERY MCP tool call (and mcp_tools on every turn), so the per-call disk read was a
# hot-path tax. Caching the text and parsing per call keeps the uncached semantics
# exactly — every caller still gets fresh objects it may mutate before saving.
# Writes go through _save_mcp_servers (jsonstore's atomic replace), which bumps the
# mtime and invalidates naturally — including edits by another process.
_MCP_CACHE: dict = {"mtime": None, "text": ""}


def _load_mcp_servers() -> list[dict]:
    try:
        mtime = MCP_FILE.stat().st_mtime_ns
    except OSError:
        return []
    if _MCP_CACHE["mtime"] != mtime:
        try:
            _MCP_CACHE.update({"mtime": mtime,
                               "text": MCP_FILE.read_text(encoding="utf-8")})
        except OSError:
            return []
    try:
        data = json.loads(_MCP_CACHE["text"])
        return data if isinstance(data, list) else []
    except Exception:  # noqa: BLE001 - corrupt file reads as empty, like load_json
        return []


def _save_mcp_servers(items: list[dict]):
    jsonstore.save_json(MCP_FILE, items)


# NOTE: the per-call spawn helpers (_run_async / _mcp_session /
# _mcp_discover_async / _mcp_call_async) were removed in favor of the
# single-spawn mcp_registry, which keeps ONE persistent ClientSession per
# server (reused across calls) with per-call timeouts and clean shutdown.


def _mcp_auth_key(sid: str) -> str:
    return f"mcp:{sid}:auth_token"


def _bundled_node() -> str:
    """Path to the desktop shell's bundled Node runtime, or "" when absent. The Tauri
    shell sets OCD_NODE when it spawns this backend so .mcpb extensions that launch
    `node` work on machines with no system Node — the packaged app ships its own
    runtime, mirroring the ${PYTHON} substitution for bundled-Python extensions."""
    p = os.getenv("OCD_NODE", "").strip()
    return p if p and Path(p).is_file() else ""


def _resolve_cfg(cfg: dict) -> dict:
    """Resolve a stored MCP server cfg for connection: expand portable placeholders
    (${PYTHON}, ${REPO_ROOT}) for stdio, and inject the auth Bearer header (from the
    keychain, never mcp_servers.json) for remote servers."""
    import sys
    repl = {"${PYTHON}": sys.executable, "${REPO_ROOT}": str(config.REPO_ROOT)}

    def _sub(s):
        if isinstance(s, str):
            for k, v in repl.items():
                s = s.replace(k, v)
        return s

    out = dict(cfg)
    out["env"] = cfg.get("env") or None
    if cfg.get("url"):
        headers = dict(cfg.get("headers") or {})
        if cfg.get("auth"):
            from . import secrets
            token = secrets.get_secret_store().get(_mcp_auth_key(cfg["id"]))
            if token:
                headers["Authorization"] = f"Bearer {token}"
        out["headers"] = headers or None
        # OAuth 2.1 connectors attach an httpx.Auth provider that adds the stored token
        # and refreshes it silently (raising ReauthorizationRequired if re-login needed).
        if cfg.get("auth_mode") == "oauth":
            from . import mcp_oauth
            out["auth_provider"] = mcp_oauth.background_provider(cfg["id"], cfg["url"])
    else:
        out["command"] = _sub(cfg.get("command", ""))
        out["args"] = [_sub(a) for a in cfg.get("args", [])]
        # Preflight the executable so a missing CLI fails with an ACTIONABLE message
        # instead of the OS's raw spawn error ("[WinError 2] The system cannot find
        # the file specified" told a user nothing about WHICH file). shutil.which
        # mirrors the spawn search — PATH, PATHEXT on Windows (docker.exe, npx.cmd),
        # and absolute paths — and re-runs on every connect, so installing the tool
        # and pressing Retry recovers without restarting the app.
        if out["command"] and not shutil.which(out["command"]):
            node = _bundled_node() if out["command"] in ("node", "node.exe") else ""
            if node:
                # No system Node, but the desktop shell bundles one: launch with it,
                # and put its dir first on PATH so anything the server spawns
                # (`#!/usr/bin/env node`, npm shims) resolves the same runtime.
                out["command"] = node
                env = dict(out.get("env") or {})
                env["PATH"] = (str(Path(node).parent) + os.pathsep
                               + env.get("PATH", os.environ.get("PATH", "")))
                out["env"] = env
            else:
                raise FileNotFoundError(
                    f"'{out['command']}' was not found on this machine. Install it and "
                    f"try again — if it was installed just now, restart the app so the "
                    f"updated PATH is picked up, then press Retry.")
    return out


def add_mcp_server(name: str, command: str = "", args: list[str] | None = None, *,
                   url: str = "", transport: str = "", env: dict | None = None,
                   headers: dict | None = None, auth_token: str = "") -> dict:
    """Register an MCP server (stdio command OR a remote Streamable-HTTP/SSE url) and
    cache its tool specs. A remote auth token is stored in the OS keychain, never in
    mcp_servers.json. Discovery happens now so the tool list assembles synchronously."""
    sid = _slug(name)
    items = [s for s in _load_mcp_servers() if s["id"] != sid]
    if url.strip():
        item = {"id": sid, "name": name.strip() or sid,
                "transport": (transport.strip().lower() or "http"),
                "url": url.strip(), "env": env or {},
                "headers": headers or {}, "auth": bool(auth_token)}
    else:
        item = {"id": sid, "name": name.strip() or sid, "transport": "stdio",
                "command": command.strip(), "args": args or [], "env": env or {}}
    if auth_token:
        from . import secrets
        secrets.get_secret_store().set(_mcp_auth_key(sid), auth_token)
    try:
        # Bounded so a slow/hung server can't block the add request for ~70s (the
        # per-call default). A server that needs longer registers as errored below.
        item["tools"] = mcp_registry.registry.discover(
            _resolve_cfg(item), timeout=config.MCP_ADD_TIMEOUT_SEC)
        item["status"] = "connected"
        item["detail"] = f"{len(item['tools'])} tools"
    except TimeoutError:
        item["tools"] = []
        item["status"] = "error"
        item["detail"] = (f"connection timed out after {config.MCP_ADD_TIMEOUT_SEC}s — "
                          "a first run may still be downloading the server (npx/uvx "
                          "packages, docker images); press Retry once it's had time "
                          "to finish")
    except Exception as e:
        item["tools"] = []
        item["status"] = "error"
        item["detail"] = str(e)[:300]
    items.append(item)
    _save_mcp_servers(items)
    return item


def add_oauth_mcp_server(name: str, url: str, transport: str = "http") -> dict:
    """Register a remote MCP server that authenticates via OAuth 2.1. Discovery is
    deferred until the user completes the interactive authorize (``authorize_mcp_oauth``),
    since it requires a browser round-trip. The server starts in an 'unauthorized' state."""
    sid = _slug(name)
    items = [s for s in _load_mcp_servers() if s["id"] != sid]
    item = {"id": sid, "name": name.strip() or sid,
            "transport": (transport.strip().lower() or "http"),
            "url": url.strip(), "env": {}, "headers": {},
            "auth": False, "auth_mode": "oauth",
            "tools": [], "status": "unauthorized",
            "detail": "Authorize to connect."}
    items.append(item)
    _save_mcp_servers(items)
    return item


def authorize_mcp_oauth(sid: str, open_url=None) -> dict:
    """Drive the interactive OAuth 2.1 authorize for an ``auth_mode=oauth`` server:
    start a loopback listener, open the provider's authorize URL in the browser, wait for
    the redirect, let the SDK exchange the code (tokens land in the keychain), then
    discover the server's tools. The loopback listener and the MCP session share one event
    loop, so the callback resolves in-band. Returns the updated server record.

    NOTE: the browser round-trip is exercised against a live OAuth MCP server; here we
    verify the wiring (provider construction, registration, status) with unit tests.
    """
    import asyncio

    from . import mcp_oauth
    s = _find_mcp(sid)
    if not s or not s.get("url") or s.get("auth_mode") != "oauth":
        raise ValueError("Not an OAuth MCP server.")
    opener = open_url or mcp_oauth.open_in_browser

    async def _run() -> tuple[list[dict], str]:
        import contextlib as _ctx

        from mcp import ClientSession

        catcher = mcp_oauth.LoopbackAuthCatcher()
        redirect_uri = await catcher.start()
        provider = mcp_oauth.interactive_provider(
            sid, s["url"], redirect_uri, open_url=opener, callback=catcher.wait)
        try:
            # Transport-aware: legacy SSE connectors authorize too (P1-6), not just
            # Streamable-HTTP.
            async with _ctx.AsyncExitStack() as stack:
                if (s.get("transport") or "http").lower() == "sse":
                    from mcp.client.sse import sse_client
                    read, write = await stack.enter_async_context(
                        sse_client(s["url"], auth=provider))
                else:
                    from mcp.client.streamable_http import streamablehttp_client
                    read, write, _ = await stack.enter_async_context(
                        streamablehttp_client(s["url"], auth=provider))
                session = await stack.enter_async_context(ClientSession(read, write))
                await session.initialize()  # triggers the OAuth flow on a 401
                resp = await session.list_tools()
                tools = [{"name": t.name, "description": t.description or "",
                          "inputSchema": getattr(t, "inputSchema", None) or {}}
                         for t in resp.tools]
            return tools, ""
        finally:
            await catcher.close()

    items = _load_mcp_servers()
    server = next((x for x in items if x["id"] == sid), None)
    try:
        tools, _ = asyncio.run(_run())
        if server is not None:
            server["tools"] = tools
            server["status"] = "connected"
            server["detail"] = f"{len(tools)} tools"
    except Exception as e:
        if server is not None:
            server["status"] = "error"
            server["detail"] = str(e)[:300]
    _save_mcp_servers(items)
    return next((x for x in _load_mcp_servers() if x["id"] == sid), server or {})


# --------------------------------------------------------------------------- #
#  Desktop extension bundles (.mcpb / legacy .dxt)
#
#  A bundle is a plain zip with a manifest.json at its root describing a bundled
#  MCP server (Claude Desktop's one-click-install format). We validate + unpack it
#  and register the server through the normal MCP path so its tools join the
#  agent's toolset. The manifest schema is an open, documented convention — this is
#  an original parser, not vendored code.
# --------------------------------------------------------------------------- #
class McpbError(Exception):
    """Raised when a .mcpb/.dxt bundle is malformed, unsafe, or missing config."""


_MCPB_VAR = re.compile(r"\$\{([^}]+)\}")


def _mcpb_read_manifest(zf: zipfile.ZipFile) -> dict:
    try:
        raw = zf.read("manifest.json")
    except KeyError:
        raise McpbError("bundle has no manifest.json at its root") from None
    try:
        m = json.loads(raw.decode("utf-8"))
    except Exception as e:  # noqa: BLE001 - report any parse failure as a clean error
        raise McpbError(f"manifest.json is not valid JSON: {e}") from e
    if not isinstance(m, dict):
        raise McpbError("manifest.json must be a JSON object")
    return m


def _mcpb_resolve_user_config(manifest: dict, provided: dict) -> dict:
    """Merge caller-provided user_config over manifest defaults and enforce that
    every `required` field ends up with a value. Returns the effective mapping."""
    spec = manifest.get("user_config")
    if not isinstance(spec, dict):
        return dict(provided)
    final = dict(provided)
    for key, s in spec.items():
        if key not in final and isinstance(s, dict) and "default" in s:
            final[key] = s["default"]
    missing = [k for k, s in spec.items()
               if isinstance(s, dict) and s.get("required") and final.get(k) in (None, "")]
    if missing:
        raise McpbError("missing required user_config: " + ", ".join(sorted(missing)))
    return final


def _mcpb_subst(value, dirname: str, user_values: dict):
    """Expand ${__dirname}, ${user_config.<key>}, and ${HOME} in a string / list of
    strings / string-valued dict. Unknown placeholders are left intact."""
    def one(s: str) -> str:
        def repl(m: re.Match) -> str:
            key = m.group(1).strip()
            if key == "__dirname":
                return dirname
            if key.startswith("user_config."):
                return str(user_values.get(key[len("user_config."):], ""))
            if key == "HOME":
                return os.path.expanduser("~")
            return m.group(0)
        return _MCPB_VAR.sub(repl, s)

    if isinstance(value, str):
        return one(value)
    if isinstance(value, list):
        return [one(x) if isinstance(x, str) else x for x in value]
    if isinstance(value, dict):
        return {k: (one(v) if isinstance(v, str) else v) for k, v in value.items()}
    return value


def _mcpb_safe_extract(zf: zipfile.ZipFile, dest: Path) -> None:
    """Extract every member under ``dest``, rejecting path-traversal ("zip slip")
    entries (absolute paths or ``..`` escapes) BEFORE writing anything to disk."""
    root = dest.resolve()
    for info in zf.infolist():
        name = info.filename
        if not name or name.endswith("/"):
            continue  # directory entries are created implicitly on member extract
        target = (dest / name).resolve()
        if target != root and root not in target.parents:
            raise McpbError(f"unsafe path in bundle: {name}")
    try:
        zf.extractall(dest)  # safe: every member validated against dest above
    except Exception as e:  # noqa: BLE001 - corrupt member CRCs raise lazily here
        raise McpbError(f"bundle extraction failed: {str(e)[:200]}") from e


def mcpb_manifest_info(path: str | Path) -> dict:
    """Read a bundle's manifest without installing — lets a UI collect user_config
    up front. Returns name/version/description/author and the raw user_config spec."""
    src = Path(path)
    if not src.is_file():
        raise McpbError(f"bundle not found: {src}")
    try:
        with zipfile.ZipFile(src) as zf:
            m = _mcpb_read_manifest(zf)
    except zipfile.BadZipFile:
        raise McpbError("not a valid .mcpb/.dxt archive (bad zip)") from None
    return {"name": str(m.get("name") or ""), "version": str(m.get("version") or ""),
            "description": str(m.get("description") or "")[:400],
            "author": m.get("author") or {}, "user_config": m.get("user_config") or {}}


def install_mcpb(path: str | Path, user_values: dict | None = None) -> dict:
    """Install a Claude-Desktop-style extension bundle (.mcpb / legacy .dxt).

    Validates the manifest and required user_config, unpacks the (path-traversal-
    checked) archive under extensions/<name>/, resolves the server launch config
    (${__dirname}, ${user_config.*}), then registers it via ``add_mcp_server`` so
    its tools become available to the agent. Returns the persisted server record.
    """
    src = Path(path)
    if not src.is_file():
        raise McpbError(f"bundle not found: {src}")
    try:
        zf = zipfile.ZipFile(src)
    except zipfile.BadZipFile:
        raise McpbError("not a valid .mcpb/.dxt archive (bad zip)") from None

    with zf:
        manifest = _mcpb_read_manifest(zf)
        name = str(manifest.get("name") or "").strip()
        if not name:
            raise McpbError("manifest.json is missing 'name'")
        server = manifest.get("server")
        if not isinstance(server, dict):
            raise McpbError("manifest.json is missing a 'server' object")
        mcp_config = server.get("mcp_config")
        if not isinstance(mcp_config, dict) or not mcp_config.get("command"):
            raise McpbError("manifest server.mcp_config.command is required")
        # Fail fast on missing config BEFORE we touch the filesystem.
        resolved_uc = _mcpb_resolve_user_config(manifest, user_values or {})

        # Extract into a staging dir and swap only on success: a bad bundle (zip
        # slip, corrupt member, disk full) must never destroy a working install —
        # update_mcpb feeds remotely downloaded assets straight through here.
        dest = EXTENSIONS_DIR / _slug(name)
        staging = EXTENSIONS_DIR / (_slug(name) + ".staging")
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
        staging.mkdir(parents=True, exist_ok=True)
        try:
            _mcpb_safe_extract(zf, staging)
        except Exception:
            shutil.rmtree(staging, ignore_errors=True)
            raise
        if dest.exists():
            shutil.rmtree(dest, ignore_errors=True)
        staging.rename(dest)

    # An update must not silently undo the user's per-tool switches (P1-12 is also
    # the dispatch-time allowlist) — remember them across the re-register below.
    prev = next((s for s in _load_mcp_servers() if s["id"] == _slug(name)), None)
    prev_disabled = set(prev.get("disabled_tools", [])) if prev else set()

    dirname = str(dest.resolve())
    command = _mcpb_subst(mcp_config["command"], dirname, resolved_uc)
    args = _mcpb_subst(mcp_config.get("args") or [], dirname, resolved_uc)
    env = _mcpb_subst(mcp_config.get("env") or {}, dirname, resolved_uc)
    # Prefer the app's bundled/frozen interpreter over whatever "python" resolves to
    # on PATH — the packaged desktop app ships without a system Python.
    if command in ("python", "python3"):
        command = "${PYTHON}"

    item = add_mcp_server(name, command, list(args), env=env or None)

    # Tag the persisted record so uninstall can reclaim the unpacked files and the
    # UI can show manifest metadata / an update path. Only a parseable GitHub URL
    # is recorded — anything else can never be checked, so the UI shouldn't offer it.
    repo = manifest.get("repository")
    repo_url = repo.get("url") if isinstance(repo, dict) else repo
    candidate = str(repo_url or manifest.get("homepage") or "")
    items = _load_mcp_servers()
    for s in items:
        if s["id"] == item["id"]:
            s["source"] = "mcpb"
            s["dir"] = dirname
            s["version"] = str(manifest.get("version") or "")
            s["description"] = str(manifest.get("description") or "")[:200]
            s["repository"] = candidate if _gh_repo_of(candidate) else ""
            if prev_disabled:
                # Prune to tools that still exist; on a failed discovery (no tool
                # list yet) keep everything rather than forget the user's choices.
                names = {t.get("name") for t in s.get("tools", [])}
                s["disabled_tools"] = sorted(prev_disabled & names if names else prev_disabled)
            item = s
            break
    _save_mcp_servers(items)

    # Remember the user's config answers (API keys, paths…) in the OS keychain —
    # never in mcp_servers.json — so a later update can re-resolve the new manifest
    # without asking for everything again.
    if resolved_uc:
        from . import secrets
        with contextlib.suppress(Exception):
            secrets.get_secret_store().set(
                _mcpb_user_config_key(item["id"]),
                json.dumps({k: str(v) for k, v in resolved_uc.items()}))
    return item


def _mcpb_user_config_key(sid: str) -> str:
    return f"mcp:{sid}:user_config"


_GH_REPO = re.compile(r"github\.com[:/]([\w.-]+)/([\w.-]+?)(?:\.git)?/?$")


def _gh_repo_of(url: str) -> tuple[str, str] | None:
    """(owner, repo) from a GitHub URL (https or git@, optional .git), else None."""
    m = _GH_REPO.search((url or "").strip())
    return (m.group(1), m.group(2)) if m else None


def _ver_key(v: str) -> tuple[int, ...]:
    """Order versions by their numeric runs ("v1.2.10" > "1.2.9") — good enough for
    release tags without a semver dependency. Unparseable strings sort lowest."""
    return tuple(int(n) for n in re.findall(r"\d+", v or "")) or (-1,)


def check_mcpb_update(sid: str) -> dict:
    """Check GitHub Releases for a newer bundle of an installed .mcpb extension,
    using the repository URL recorded from its manifest at install time (P1-13).
    Returns {current, latest, url, notes, tag}; ``latest`` is None when current."""
    s = _find_mcp(sid)
    if not s or s.get("source") != "mcpb":
        raise McpbError("not an installed extension")
    repo = _gh_repo_of(s.get("repository", ""))
    if not repo:
        raise McpbError("this extension's manifest declares no GitHub repository "
                        "to check for updates")
    try:
        r = _http_get(f"https://api.github.com/repos/{repo[0]}/{repo[1]}/releases/latest",
                      {"Accept": "application/vnd.github+json", "User-Agent": _UA})
    except Exception as e:
        raise McpbError("update check failed — GitHub is unreachable "
                        f"({str(e)[:120] or type(e).__name__})") from e
    if r.status_code != 200:
        raise McpbError(f"GitHub release lookup failed (HTTP {r.status_code})")
    try:
        rel = r.json()
    except Exception as e:
        raise McpbError("GitHub returned an unexpected (non-JSON) response") from e
    asset = next((a for a in rel.get("assets", [])
                  if str(a.get("name", "")).lower().endswith((".mcpb", ".dxt"))), None)
    if not asset:
        raise McpbError("the latest release has no .mcpb/.dxt asset")
    tag = str(rel.get("tag_name") or rel.get("name") or "")
    current = str(s.get("version") or "")
    out = {"current": current, "latest": None, "url": "", "notes": "", "tag": tag}
    # Numeric compare against the manifest version, PLUS tag identity against the
    # release we last installed — a repo whose tags carry more numeric runs than
    # its manifest version (tag v1.2.0, manifest "1.2"; date tags) would otherwise
    # look forever-newer and offer the same update in a loop.
    if tag != str(s.get("release_tag") or "") and _ver_key(tag) > _ver_key(current):
        out.update({"latest": tag.lstrip("vV"),
                    "url": str(asset.get("browser_download_url") or ""),
                    "notes": str(rel.get("body") or "")[:400]})
    return out


def update_mcpb(sid: str, user_values: dict | None = None) -> dict:
    """Download the newest release bundle and reinstall it in place (P1-13).

    The install-time user_config answers come back from the OS keychain and merge
    under any newly provided values — so an update that adds a required field fails
    with the same "missing required user_config" error the install UI already
    prompts for, and everything else updates with one click."""
    import tempfile
    info = check_mcpb_update(sid)
    if not info.get("latest"):
        raise McpbError("already up to date")
    stored: dict = {}
    from . import secrets
    with contextlib.suppress(Exception):
        raw = secrets.get_secret_store().get(_mcpb_user_config_key(sid))
        stored = json.loads(raw) if raw else {}
    if not isinstance(stored, dict):
        stored = {}
    values = {**stored, **(user_values or {})}
    try:
        r = _http_get(info["url"], {"User-Agent": _UA, "Accept": "application/octet-stream"},
                      timeout=120)
    except Exception as e:
        raise McpbError(f"bundle download failed ({str(e)[:120] or type(e).__name__})") from e
    if r.status_code != 200:
        raise McpbError(f"bundle download failed (HTTP {r.status_code})")
    # Retire the running server only now, with the new bundle fully downloaded —
    # keeps the window where a tool call could respawn the old config as narrow
    # as the reinstall itself.
    s = _find_mcp(sid)
    if s:
        with contextlib.suppress(Exception):
            mcp_registry.registry.drop(_resolve_cfg(s))
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".mcpb")
    try:
        tmp.write(r.content)
        tmp.close()
        item = install_mcpb(tmp.name, values)
    finally:
        Path(tmp.name).unlink(missing_ok=True)

    # Remember which release we just installed (see check_mcpb_update's tag-identity
    # guard), and — if the new manifest RENAMED the extension — retire the old
    # record so it doesn't linger half-updated next to the new one.
    items = _load_mcp_servers()
    for rec in items:
        if rec["id"] == item["id"]:
            rec["release_tag"] = info.get("tag", "")
            item = rec
            break
    _save_mcp_servers(items)
    if item["id"] != sid:
        with contextlib.suppress(Exception):
            remove_mcp_server(sid)
    return item


def remove_mcp_server(sid: str):
    items = _load_mcp_servers()
    for s in items:
        if s["id"] == sid:
            mcp_registry.registry.drop(_resolve_cfg(s))  # terminate the persistent session
            if s.get("auth"):
                from . import secrets
                with contextlib.suppress(Exception):
                    secrets.get_secret_store().delete(_mcp_auth_key(sid))
            # Forget any OAuth tokens + dynamic client registration for this connector.
            if s.get("auth_mode") == "oauth":
                from . import mcp_oauth
                mcp_oauth.clear_oauth(sid)
            # Reclaim a .mcpb extension's unpacked files, but only if the recorded
            # dir really lives under EXTENSIONS_DIR (never rmtree an arbitrary path).
            if s.get("source") == "mcpb":
                from . import secrets
                with contextlib.suppress(Exception):
                    secrets.get_secret_store().delete(_mcpb_user_config_key(sid))
                if s.get("dir"):
                    d = Path(s["dir"]).resolve()
                    if EXTENSIONS_DIR.resolve() in d.parents:
                        shutil.rmtree(d, ignore_errors=True)
    _save_mcp_servers([s for s in items if s["id"] != sid])


def refresh_mcp_server(sid: str) -> dict:
    """Re-connect a server from scratch (the error card's Retry): kill any live
    session, respawn, and re-discover with the same generous first-run timeout as
    add — a cold `npx`/`docker` download that timed out usually succeeds here."""
    items = _load_mcp_servers()
    for s in items:
        if s["id"] == sid:
            try:
                mcp_registry.registry.drop(_resolve_cfg(s))  # respawn with fresh state
                s["tools"] = mcp_registry.registry.discover(
                    _resolve_cfg(s), timeout=config.MCP_ADD_TIMEOUT_SEC)
                s["status"] = "connected"
                s["detail"] = f"{len(s['tools'])} tools"
            except TimeoutError:
                s["status"] = "error"
                s["detail"] = (f"still timing out after {config.MCP_ADD_TIMEOUT_SEC}s — "
                               "check that the command runs in a terminal")
            except Exception as e:
                s["status"] = "error"
                s["detail"] = str(e)[:300]
            _save_mcp_servers(items)
            return s
    return {}


def _find_mcp(sid: str) -> dict | None:
    for s in _load_mcp_servers():
        if s["id"] == sid:
            return s
    return None


def mcp_resources(sid: str) -> list[dict]:
    """List an MCP server's resources ([] if it declares none / doesn't support them)."""
    s = _find_mcp(sid)
    if not s:
        return []
    with contextlib.suppress(Exception):
        return mcp_registry.registry.list_resources(_resolve_cfg(s))
    return []


def mcp_read_resource(sid: str, uri: str) -> str:
    s = _find_mcp(sid)
    if not s:
        return ""
    return mcp_registry.registry.read_resource(_resolve_cfg(s), uri)


def mcp_prompts(sid: str) -> list[dict]:
    """List an MCP server's prompts ([] if it declares none / doesn't support them)."""
    s = _find_mcp(sid)
    if not s:
        return []
    with contextlib.suppress(Exception):
        return mcp_registry.registry.list_prompts(_resolve_cfg(s))
    return []


def mcp_get_prompt(sid: str, name: str, args: dict | None = None) -> dict:
    s = _find_mcp(sid)
    if not s:
        return {"messages": []}
    return mcp_registry.registry.get_prompt(_resolve_cfg(s), name, args or {})


def _oauth_authorized(s: dict) -> bool:
    if s.get("auth_mode") != "oauth":
        return False
    from . import mcp_oauth
    return mcp_oauth.has_tokens(s["id"])


def _backfill_mcpb_repository(items: list[dict]) -> bool:
    """Extensions installed before the update feature have no `repository` recorded.
    Read it once from the unpacked manifest.json (and persist — even as "") so the
    update button appears for them without a remove/reinstall. Returns whether
    anything changed."""
    changed = False
    for s in items:
        if s.get("source") == "mcpb" and "repository" not in s:
            url = ""
            with contextlib.suppress(Exception):
                m = json.loads((Path(s.get("dir", "")) / "manifest.json")
                               .read_text(encoding="utf-8"))
                repo = m.get("repository")
                cand = str((repo.get("url") if isinstance(repo, dict) else repo)
                           or m.get("homepage") or "")
                url = cand if _gh_repo_of(cand) else ""
            s["repository"] = url
            changed = True
    return changed


def list_mcp_servers() -> list[dict]:
    """Registered MCP servers (tool NAMES included for the per-tool toggles, but not
    the verbose cached schemas)."""
    items = _load_mcp_servers()
    if _backfill_mcpb_repository(items):
        _save_mcp_servers(items)
    return [{"id": s["id"], "name": s["name"], "transport": s.get("transport", "stdio"),
             "command": s.get("command", ""), "args": s.get("args", []),
             "url": s.get("url", ""), "auth": bool(s.get("auth")),
             "auth_mode": s.get("auth_mode", ""), "authorized": _oauth_authorized(s),
             "source": s.get("source", ""), "version": s.get("version", ""),
             "repository": s.get("repository", ""),
             "status": s.get("status", "unknown"), "detail": s.get("detail", ""),
             "tool_count": len(s.get("tools", [])),
             "tools": [t.get("name", "") for t in s.get("tools", [])],
             "disabled_tools": s.get("disabled_tools", [])}
            for s in items]


def set_mcp_tool_enabled(sid: str, tool_name: str, enabled: bool) -> dict | None:
    """Enable/disable ONE tool within a connector (P1-12). Disabled tools are left out
    of the turn's tool assembly, so the model never sees them — and the dispatch-time
    allowlist (H6) means an injected call can't reach them either. Persisted on the
    server record."""
    items = _load_mcp_servers()
    server = next((s for s in items if s["id"] == sid), None)
    if server is None:
        return None
    disabled = set(server.get("disabled_tools", []))
    if enabled:
        disabled.discard(tool_name)
    else:
        disabled.add(tool_name)
    server["disabled_tools"] = sorted(disabled)
    _save_mcp_servers(items)
    return next(s for s in list_mcp_servers() if s["id"] == sid)


def mcp_oauth_status(sid: str) -> dict:
    """OAuth authorization status for a connector (never returns the token itself)."""
    from . import mcp_oauth
    return mcp_oauth.summarize_tokens(sid)


def mcp_tools(enabled_ids: list[str]) -> list[dict]:
    """Agent tool specs for the enabled MCP servers, named mcp_<sid>_<tool>.
    Tools the user disabled individually (P1-12) are left out — combined with the
    dispatch-time allowlist, they are unreachable for the turn."""
    out: list[dict] = []
    for s in _load_mcp_servers():
        if s["id"] not in enabled_ids:
            continue
        disabled = set(s.get("disabled_tools", []))
        for t in s.get("tools", []):
            if t.get("name") in disabled:
                continue
            out.append({"type": "function", "function": {
                "name": f"mcp_{s['id']}_{t['name']}",
                "description": (t.get("description")
                               or f"{s['name']} · {t['name']}")[:1000],
                "parameters": t.get("inputSchema") or {"type": "object",
                                                        "properties": {}}}})
    return out


# A tool result carrying one of these means the connector needs re-auth, not that
# the model learned a fact — so we tag it to stop the agent inventing conclusions.
_AUTH_FAILURE_SIGNATURES = (
    "reauthentication", "gcloud auth", "application-default login", "invalid_grant",
    "invalid_rapt", "refresherror", "could not automatically determine credentials",
    "unauthorized", "permission denied", "access token", "not authenticated",
)


def _tag_auth_failure(result: str) -> str:
    """If a tool result reads like an auth failure, append a directive so a weak model
    doesn't treat the error text as data and hallucinate about the app."""
    if any(sig in result.lower() for sig in _AUTH_FAILURE_SIGNATURES):
        return (result + "\n\n[TOOL UNAVAILABLE — authentication problem. Do NOT infer "
                "anything about this application or its design from this error. Either "
                "answer from your own knowledge or tell the user the connector needs to "
                "be reconnected. Do not retry this tool.]")
    return result


def coerce_args_to_schema(args: dict, schema: dict) -> dict:
    """Best-effort repair of LLM-emitted argument types against the tool's JSON schema.

    Models (especially smaller BYOK ones) often stringify structured values —
    ``"[0, 0]"`` for an array, ``"true"`` for a boolean, ``"3"`` for an integer —
    which strict (pydantic-validated) MCP servers reject verbatim, and a weak model
    can then burn its whole step budget re-issuing the same failing call. Coerce ONLY
    when the value is a string and the parsed result matches the declared type;
    everything else passes through untouched so the server's own validation stays the
    source of truth."""
    props = (schema or {}).get("properties")
    if not isinstance(args, dict) or not isinstance(props, dict):
        return args
    out = dict(args)
    for key, val in args.items():
        spec = props.get(key)
        if not isinstance(spec, dict) or not isinstance(val, str):
            continue
        t = spec.get("type")
        if isinstance(t, list):  # union like ["array", "null"] — first concrete type
            t = next((x for x in t if x != "null"), None)
        try:
            if t in ("array", "object"):
                parsed = json.loads(val)
                if (t == "array" and isinstance(parsed, list)) or \
                        (t == "object" and isinstance(parsed, dict)):
                    out[key] = parsed
            elif t == "integer":
                out[key] = int(val.strip())
            elif t == "number":
                out[key] = float(val.strip())
            elif t == "boolean":
                low = val.strip().lower()
                if low in ("true", "false"):
                    out[key] = low == "true"
        except (ValueError, json.JSONDecodeError):
            pass  # leave as-is; the server's error message will guide the model
    return out


def call_mcp(full_name: str, args: dict) -> str:
    for s in _load_mcp_servers():
        prefix = f"mcp_{s['id']}_"
        if full_name.startswith(prefix):
            tool = full_name[len(prefix):]
            spec = next((t for t in s.get("tools", []) if t["name"] == tool), None)
            if spec is not None:
                try:
                    coerced = coerce_args_to_schema(args or {}, spec.get("inputSchema") or {})
                    return _tag_auth_failure(mcp_registry.registry.call(_resolve_cfg(s), tool, coerced))
                except Exception as e:
                    return _tag_auth_failure(f"MCP '{s['id']}' call failed: {str(e)[:200]}")
    return f"MCP tool '{full_name}' not found."


# --------------------------------------------------------------------------- #
#  Unified tool dispatch + assembly (plugins + connectors + MCP)
# --------------------------------------------------------------------------- #
def agent_tools(enabled_plugins: list[str], enabled_connectors: list[str],
                enabled_mcp: list[str] | None = None) -> list[dict]:
    return (plugin_tools(enabled_plugins) + connector_tools(enabled_connectors)
            + mcp_tools(enabled_mcp or []))


def run_tool(name: str, args: dict) -> str:
    if name.startswith("rest_"):
        return call_connector(name[len("rest_"):], args.get("path", ""))
    if name.startswith("mcp_"):
        return call_mcp(name, args)
    return run_plugin(name, args)


# --------------------------------------------------------------------------- #
#  Web search — pluggable provider
#
#  Two backends behind one seam so the agent's research quality never depends on a
#  single scraped endpoint:
#    * "searxng" — a privacy-respecting metasearch engine with a clean JSON API,
#      free and self-hostable. The recommended option (set searxng_url in settings);
#      because it can run on localhost, its URL is trusted (not SSRF-filtered).
#    * "ddg"     — the keyless DuckDuckGo HTML endpoint, kept as a zero-config
#      fallback and used automatically when SearXNG is unset or unreachable.
# --------------------------------------------------------------------------- #
_DDG_URL = "https://html.duckduckgo.com/html/"
_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")


def _clean_ddg_url(href: str) -> str:
    """DDG HTML results wrap targets in /l/?uddg=<encoded>. Unwrap to the real URL."""
    from urllib.parse import parse_qs, unquote, urlparse
    href = (href or "").strip()
    if href.startswith("//"):
        href = "https:" + href
    try:
        p = urlparse(href)
        if "duckduckgo.com" in p.netloc and p.path.startswith("/l/"):
            q = parse_qs(p.query)
            if q.get("uddg"):
                return unquote(q["uddg"][0])
    except Exception:
        pass
    return href


def _domain(url: str) -> str:
    from urllib.parse import urlparse
    try:
        net = urlparse(url).netloc
        return net[4:] if net.startswith("www.") else net
    except Exception:
        return ""


def _result_item(title: str, url: str, snippet: str) -> dict | None:
    """Normalize one hit into {title, url, snippet, domain, favicon}, or None if it
    lacks a title/url."""
    title = (title or "").strip()
    url = (url or "").strip()
    snippet = (snippet or "").strip()
    if not (title and url):
        return None
    dom = _domain(url)
    return {"title": title, "url": url, "snippet": snippet, "domain": dom,
            "favicon": (f"https://www.google.com/s2/favicons?domain={dom}&sz=64"
                        if dom else "")}


def _parse_ddg_html(html: str, n: int) -> list[dict]:
    """Extract structured results from a DuckDuckGo HTML SERP. Pure (no network) so it
    can be unit-tested against a fixture."""
    out: list[dict] = []
    for m in re.finditer(
            r'result__a"[^>]*href="(.*?)".*?>(.*?)</a>.*?'
            r'result__snippet"[^>]*>(.*?)</a>', html or "", re.DOTALL):
        url = _clean_ddg_url(re.sub(r"<.*?>", "", m.group(1)).strip())
        title = re.sub(r"<.*?>", "", m.group(2)).strip()
        snippet = re.sub(r"<.*?>", "", m.group(3)).strip()
        item = _result_item(title, url, snippet)
        if item:
            out.append(item)
        if len(out) >= n:
            break
    return out


def _parse_searxng_json(data: dict, n: int) -> list[dict]:
    """Map a SearXNG JSON response ({"results":[{title,url,content}...]}) to our shape.
    Pure (no network) for unit testing."""
    out: list[dict] = []
    for r in (data or {}).get("results", []) if isinstance(data, dict) else []:
        if not isinstance(r, dict):
            continue
        item = _result_item(r.get("title", ""), r.get("url", ""), r.get("content", ""))
        if item:
            out.append(item)
        if len(out) >= n:
            break
    return out


def _search_config() -> tuple[str, str]:
    """(provider, searxng_url) from settings, defaulting to the keyless DDG backend."""
    from . import settings
    s = settings.get_settings()
    return (s.get("search_provider") or "ddg").strip().lower(), (s.get("searxng_url") or "").strip()


def _ddg_html_results(query: str, n: int) -> list[dict]:
    try:
        import httpx
        resp = httpx.post(_DDG_URL, data={"q": query}, timeout=15,
                          headers={"User-Agent": _UA})
        return _parse_ddg_html(resp.text, n)
    except Exception:
        return []


def _searxng_results(query: str, n: int, base_url: str) -> list[dict]:
    """Query a SearXNG instance's JSON API. Rejects non-http(s) URLs; localhost is fine
    (a self-hosted instance is trusted, so it is deliberately NOT SSRF-filtered)."""
    from urllib.parse import urlparse
    base = (base_url or "").strip().rstrip("/")
    if urlparse(base).scheme not in ("http", "https"):
        return []
    try:
        import httpx
        resp = httpx.get(f"{base}/search",
                         params={"q": query, "format": "json"},
                         timeout=15, headers={"User-Agent": _UA},
                         follow_redirects=True)
        return _parse_searxng_json(resp.json(), n)
    except Exception:
        return []


def _web_results(query: str, n: int = 5) -> list[dict]:
    """Structured web results via the configured provider, with a keyless DDG fallback
    whenever SearXNG is unconfigured or returns nothing."""
    query = (query or "").strip()
    if not query:
        return []
    provider, searxng_url = _search_config()
    if provider == "searxng" and searxng_url:
        results = _searxng_results(query, n, searxng_url)
        if results:
            return results
        # SearXNG down/misconfigured — degrade gracefully rather than returning nothing.
    return _ddg_html_results(query, n)


def _format_web_block(query: str, results: list[dict]) -> str:
    if not results:
        return "No query." if not (query or "").strip() else \
            f"No web results for '{query}'."
    lines = [f"- {r['title']}\n  {r['snippet']}\n  {r['url']}" for r in results]
    return "Web results:\n" + "\n".join(lines)


def web_search(query: str, n: int = 5) -> str:
    """Return a compact text block of web results for the agent to read."""
    return _format_web_block(query, _web_results(query, n))


def web_search_with_sources(query: str, n: int = 5) -> tuple[str, list[dict]]:
    """Like web_search, but also returns the structured sources for the UI."""
    results = _web_results(query, n)
    return _format_web_block(query, results), results


# --------------------------------------------------------------------------- #
#  Research — parallel multi-source synthesis
# --------------------------------------------------------------------------- #
def _research_subqueries(topic: str, n: int) -> list[str]:
    """Expand a topic into n distinct search angles (LLM, heuristic fallback)."""
    try:
        client = llm.get_llm_client()
        resp = client.chat.completions.create(
            model=config.AGENT_MODEL, temperature=0.4, max_tokens=200,
            messages=[{"role": "user", "content":
                       f"Give exactly {n} distinct web-search queries (one per line, "
                       f"no numbering, no quotes) that together research this topic "
                       f"from different angles:\n{topic}"}])
        lines = [re.sub(r"^[\-\d\.\)\s•]+", "", ln).strip()
                 for ln in (resp.choices[0].message.content or "").splitlines()]
        subs = [ln for ln in lines if ln][:n]
        if subs:
            return subs
    except Exception:
        pass
    return [topic, f"{topic} statistics", f"{topic} 2025", f"{topic} overview"][:n]


def research_with_sources(topic: str, n: int = 4) -> tuple[str, list[dict]]:
    """Run n web searches (distinct angles) IN PARALLEL; return (combined text,
    deduplicated sources)."""
    import concurrent.futures
    topic = (topic or "").strip()
    if not topic:
        return "No research topic.", []
    subs = _research_subqueries(topic, n)
    texts: dict[str, str] = {}
    sources: list[dict] = []
    seen: set[str] = set()
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(len(subs), 5)) as ex:
        futs = {ex.submit(web_search_with_sources, sq, 4): sq for sq in subs}
        for fut in concurrent.futures.as_completed(futs):
            sq = futs[fut]
            try:
                texts[sq], srcs = fut.result()
            except Exception as e:
                texts[sq], srcs = f"(search failed: {e})", []
            for s in srcs:
                if s["url"] not in seen:
                    seen.add(s["url"])
                    sources.append(s)
    blocks = [f"# Multi-source research: {topic}",
              f"(searched {len(subs)} angles in parallel)\n"]
    for sq in subs:
        blocks.append(f"## Angle: {sq}\n{texts.get(sq, '(no results)')}\n")
    return "\n".join(blocks)[:7000], sources


def research(topic: str, n: int = 4) -> str:
    """Run n web searches (over distinct angles) IN PARALLEL and combine them."""
    return research_with_sources(topic, n)[0]


# --------------------------------------------------------------------------- #
#  Claude-equivalent built-in tools — web_fetch / code_execution / bash /
#  text_editor / memory. Implemented client-side to mirror Claude's tool
#  names, input schemas, and result strings. Sandboxed for this (Windows) host:
#  file/exec tools are jailed under _sandbox / agent_memory with timeouts +
#  output caps; the powerful ones are OFF by default (enabled in the UI).
# --------------------------------------------------------------------------- #
SANDBOX_ROOT = config.REPO_ROOT / "_sandbox"
MEMORY_ROOT = config.REPO_ROOT / "agent_memory"
_FETCH_CACHE: dict = {}
# C3: 'python' intentionally NOT allowlisted — `python -c "..."` is arbitrary code
# execution that bypasses the run_python container sandbox.
_BASH_ALLOW = {"ls", "cat", "echo", "pwd", "grep", "find", "wc", "head", "tail",
               "type", "dir", "date", "whoami", "sort", "uniq", "cut"}


def _bash_arg_escapes_jail(tok: str) -> bool:
    """C2: reject a bash argument that reaches outside the sandbox.

    The command loop already sets cwd to SANDBOX_ROOT and blocks '..' and shell
    metacharacters, but ABSOLUTE-path arguments still escaped the jail (e.g.
    ``cat /etc/passwd`` or ``cat /home/user/app/.env``). Flags (leading '-') are
    fine. Anything that looks like an absolute POSIX path, a home-relative path,
    a Windows drive/UNC path, or that resolves outside SANDBOX_ROOT is rejected.
    """
    t = (tok or "").strip()
    if not t or t.startswith("-"):
        return False  # empty or a flag — not a path escape
    # Absolute / home / Windows-absolute / UNC paths never allowed.
    if t.startswith(("/", "~", "\\")):
        return True
    if len(t) >= 2 and t[1] == ":" and t[0].isalpha():  # C:\ or C:/
        return True
    # Relative token: it must resolve to somewhere inside the sandbox root.
    try:
        target = (SANDBOX_ROOT / t).resolve()
        target.relative_to(SANDBOX_ROOT.resolve())
        return False
    except Exception:
        return True


def _ensure_dir(p: Path):
    try:
        p.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass


def _cap(s: str, n: int) -> str:
    s = s or ""
    return s if len(s) <= n else s[:n] + "\n…[truncated]…"


def _scrub_secrets(s: str) -> str:
    return re.sub(r"(?i)(api[_-]?key|secret|token|password|bearer)\s*[=:]\s*\S+",
                  r"\1=***", s or "")


def _iso_now() -> str:
    from datetime import datetime
    return datetime.now().isoformat(timespec="seconds")


def _html_to_text(html_src: str) -> str:
    import html as _h
    # Drop non-content boilerplate wholesale (with their inner text) so the model sees
    # the article, not the chrome: scripts/styles, page head, nav/header/footer/aside,
    # forms/buttons, embedded frames, and no-JS fallbacks.
    s = re.sub(r"(?s)<!--.*?-->", " ", html_src)  # HTML comments
    s = re.sub(
        r"(?is)<(script|style|head|nav|header|footer|aside|form|button|iframe|noscript|"
        r"template|svg)[^>]*>.*?</\1>", " ", s)
    s = re.sub(r"(?is)<br\s*/?>", "\n", s)
    s = re.sub(r"(?is)</(p|div|h[1-6]|li|tr|section|article)>", "\n", s)
    s = re.sub(r"(?s)<[^>]+>", " ", s)
    s = _h.unescape(s)
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r"\n[ \t]*\n[ \t]*\n+", "\n\n", s)
    return s.strip()


# ---- web_fetch (default ON, read-only, SSRF-guarded) ---- #
def _blocked_host(host: str) -> bool:
    import ipaddress
    import socket
    if not host:
        return True
    try:
        infos = socket.getaddrinfo(host, None)
    except Exception:
        return True
    for info in infos:
        try:
            addr = ipaddress.ip_address(info[4][0].split("%")[0])
        except Exception:
            return True
        if (addr.is_private or addr.is_loopback or addr.is_link_local
                or addr.is_reserved or addr.is_multicast or addr.is_unspecified):
            return True
    return False


def web_fetch(url: str) -> tuple[str, list[dict]]:
    """Fetch one URL → (cleaned text for the model, source card list). http/https
    only, private/internal hosts blocked, HTML/text/JSON only."""
    import time as _t
    from urllib.parse import urlparse
    url = (url or "").strip()
    if not url:
        return "web_fetch_tool_error: invalid_input", []
    if len(url) > 250:
        return "web_fetch_tool_error: url_too_long", []
    p = urlparse(url)
    if p.scheme not in ("http", "https") or not p.netloc:
        return "web_fetch_tool_error: invalid_input", []
    if _blocked_host(p.hostname or ""):
        return "web_fetch_tool_error: url_not_allowed (private/internal host blocked)", []
    cached = _FETCH_CACHE.get(url)
    if cached and (_t.time() - cached[0] < 900):
        return cached[1], cached[2]
    try:
        import httpx
        r = httpx.get(url, headers={"User-Agent": _UA}, timeout=15,
                      follow_redirects=True)
    except Exception as e:
        return f"web_fetch_tool_error: url_not_accessible ({str(e)[:120]})", []
    final = urlparse(str(r.url)).hostname or ""
    if final and final != (p.hostname or "") and _blocked_host(final):
        return "web_fetch_tool_error: url_not_allowed (redirected to blocked host)", []
    ctype = (r.headers.get("content-type") or "").lower()
    if not any(c in ctype for c in ("text/html", "text/plain", "application/json",
                                    "application/xml", "text/xml")):
        return f"web_fetch_tool_error: unsupported_content_type ({ctype or 'unknown'})", []
    title = ""
    m = re.search(r"<title[^>]*>(.*?)</title>", r.text, re.IGNORECASE | re.DOTALL)
    if m:
        title = re.sub(r"\s+", " ", m.group(1)).strip()[:200]
    text = _html_to_text(r.text)[:24000]
    out = f"Fetched {url}\nTitle: {title}\nRetrieved: {_iso_now()}\n\n{text}"
    dom = _domain(url)
    src = [{"title": title or dom, "url": url, "snippet": text[:200].strip(),
            "domain": dom,
            "favicon": (f"https://www.google.com/s2/favicons?domain={dom}&sz=64"
                        if dom else "")}]
    _FETCH_CACHE[url] = (_t.time(), out, src)
    return out, src


# --------------------------------------------------------------------------- #
#  code_execution — real, streaming, file-producing Python execution.
#
#  Runs in the PERSISTENT per-project workspace (SANDBOX_ROOT/<project>) so files the
#  script writes (a CSV, a chart PNG…) survive the call and can be surfaced to the user
#  and browsed in the Code tab. Two engines behind the `code_execution` setting:
#    * "docker" — an isolated container (network off, memory/CPU/pids capped). Preferred.
#    * "local"  — a jailed subprocess on this device (cwd = workspace, scrubbed env,
#                 POSIX resource limits, timeout). Used when Docker is absent so the
#                 feature works out of the box; less isolation than a container.
#  "auto" picks docker-if-present else local; "off" disables it. Output streams line by
#  line via an on_output(stream, text) callback so the UI can show the run live. Every
#  run is still gated by the HITL approval prompt on interactive turns.
# --------------------------------------------------------------------------- #
_EXEC_TIMEOUT_SEC = 60
_EXEC_OUTPUT_CAP = 24_000        # max chars of combined stdout+stderr kept/streamed
_EXEC_FILE_TEXT_CAP = 400_000    # max bytes of a produced text file inlined as an artifact
_EXEC_MAX_FILES = 20
# Produced text files we can show inline as an artifact -> artifact kind. Anything else
# (images, xlsx, pdf, zip…) is surfaced as a download only.
_TEXT_FILE_KIND = {
    ".csv": "csv", ".tsv": "csv", ".json": "code", ".md": "markdown", ".markdown": "markdown",
    ".txt": "text", ".log": "text", ".py": "code", ".js": "code", ".ts": "code",
    ".html": "html", ".svg": "svg", ".xml": "code", ".yaml": "code", ".yml": "code",
    ".sql": "code", ".sh": "code",
}
_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}


def _code_execution_mode() -> str:
    from . import settings
    m = (settings.get_settings().get("code_execution") or "auto").strip().lower()
    return m if m in config.CODE_EXECUTION_MODES else "auto"


def safe_project(project: str | None) -> str:
    """Reduce a project id to a single safe path segment (slug chars only). Blocks the
    ``project=../../etc`` traversal that would otherwise let a workspace root escape
    SANDBOX_ROOT (the code tree/file/download routes all resolve paths under it)."""
    slug = re.sub(r"[^A-Za-z0-9_-]", "", project or "")
    return slug or config.GENERAL_ID


def _sync_project_knowledge(project: str | None, root: Path) -> None:
    """Mirror the project's uploaded knowledge files into the exec workspace under
    knowledge/ so code can work on the ACTUAL uploads ("modify this CSV") — RAG
    passages can answer questions about a file but cannot transform it. Copies are
    stat-compared (no-op when nothing changed, refreshed on re-upload); the mirror
    is created BEFORE the produced-files snapshot, so pristine uploads are never
    reported back as outputs, and the originals in projects/<id>/knowledge stay
    untouched whatever the code does to its copies."""
    if not project:
        return
    src = config.PROJECTS_DIR / project / "knowledge"
    if not src.is_dir():
        return
    dst = root / "knowledge"
    _ensure_dir(dst)
    for f in src.iterdir():
        if not f.is_file():
            continue
        target = dst / f.name
        try:
            st = f.stat()
            dt = target.stat() if target.exists() else None
            if dt is None or dt.st_size != st.st_size or dt.st_mtime < st.st_mtime:
                shutil.copy2(f, target)
        except OSError:
            continue  # an unreadable file must not break code execution


def _exec_workdir(project: str | None) -> Path:
    root = SANDBOX_ROOT / safe_project(project)
    _ensure_dir(root)
    _sync_project_knowledge(project, root)
    return root


def _within(root: Path, p: Path) -> bool:
    """Whether ``p`` really resolves to somewhere inside ``root`` (blocks a symlink the
    sandboxed code plants to a host file being read/surfaced)."""
    try:
        p.resolve().relative_to(root.resolve())
        return True
    except (OSError, ValueError):
        return False


def _snapshot(root: Path) -> dict:
    """Map every REAL file under ``root`` to (mtime_ns, size) so a post-run diff finds the
    files a script created or modified. Symlinks are skipped (a sandboxed script must not
    exfiltrate a host file by symlinking it in) and the private ``.exec`` scratch dir is
    ignored."""
    snap: dict = {}
    for p in root.rglob("*"):
        rel = p.relative_to(root)
        if ".exec" in rel.parts or p.is_symlink() or not p.is_file():
            continue
        if not _within(root, p):
            continue
        try:
            st = p.stat()
            snap[p] = (st.st_mtime_ns, st.st_size)
        except OSError:
            pass
    return snap


def _classify_produced(p: Path, root: Path) -> dict:
    ext = p.suffix.lower()
    text_kind = _TEXT_FILE_KIND.get(ext)
    is_image = ext in _IMAGE_EXTS
    info = {"path": p.relative_to(root).as_posix(), "size": p.stat().st_size,
            "kind": text_kind or ("image" if is_image else "binary")}
    if text_kind and info["size"] <= _EXEC_FILE_TEXT_CAP:
        try:
            info["text"] = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            pass
    return info


def _produced_files(before: dict, root: Path) -> list[dict]:
    """Files that are new or changed since ``before`` (sorted, capped)."""
    out: list[dict] = []
    for p in sorted(_snapshot(root), key=lambda x: x.as_posix()):
        try:
            st = p.stat()
        except OSError:
            continue
        if before.get(p) != (st.st_mtime_ns, st.st_size):
            try:
                out.append(_classify_produced(p, root))
            except OSError:
                continue
        if len(out) >= _EXEC_MAX_FILES:
            break
    return out


def _scrubbed_env(workdir: Path) -> dict:
    """A minimal, secret-free environment for a local run: keep only PATH/locale/temp,
    drop every API key and PYTHON* override, and point HOME at the workspace."""
    keep = ("PATH", "SYSTEMROOT", "WINDIR", "COMSPEC", "TEMP", "TMP", "LANG", "LC_ALL", "TZ")
    env = {k: os.environ[k] for k in keep if k in os.environ}
    env["HOME"] = str(workdir)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUNBUFFERED"] = "1"
    env["MPLBACKEND"] = "Agg"  # headless matplotlib (charts render to files, not a window)
    return env


def _posix_limits():  # pragma: no cover - runs only in the child process before exec
    """Best-effort resource limits for a local child (POSIX). Each cap is applied
    independently so one unsupported limit doesn't abort the run."""
    import os as _os
    import resource
    _os.setsid()  # own process group, so a timeout can kill the whole tree
    for res, soft in ((resource.RLIMIT_CPU, _EXEC_TIMEOUT_SEC + 5),
                      (resource.RLIMIT_FSIZE, 256 * 1024 * 1024),
                      (resource.RLIMIT_AS, 4 * 1024 * 1024 * 1024),  # cap memory so a run can't OOM the host
                      (resource.RLIMIT_CORE, 0)):
        try:
            resource.setrlimit(res, (soft, soft))
        except Exception:
            pass


def _isolation_popen_extra(local: bool) -> dict:
    """Popen kwargs that put the child in its OWN session/process group so a timeout can
    kill just the run's tree — never the backend's. Local also installs resource limits
    via preexec_fn (which calls setsid); Docker uses start_new_session for the CLI child."""
    import sys
    if sys.platform == "win32":
        import subprocess
        return {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
    return {"preexec_fn": _posix_limits} if local else {"start_new_session": True}


def _kill_proc(proc, own_group: bool):
    """Kill a timed-out run. Only killpg the child's process GROUP when we started it in
    its own session (``own_group``) — otherwise the child shares the backend's group and
    killpg would SIGKILL the server itself. Falls back to killing just the process."""
    import signal
    import sys
    if own_group and sys.platform != "win32":
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            return
        except Exception:
            pass
    try:
        proc.kill()
    except Exception:
        pass


def _stream_subprocess(cmd, cwd, env, on_output, timeout, stdin_data=None,
                       popen_extra=None):
    """Run ``cmd`` streaming stdout/stderr line-by-line to ``on_output(stream, text)``.
    Returns (return_code, stdout, stderr, timed_out). Output is capped at
    ``_EXEC_OUTPUT_CAP`` combined chars. The child is always started in its own session
    (``popen_extra``) so a timeout kill can't reach the backend."""
    import subprocess
    import threading
    # errors="replace": the child may print bytes that aren't valid in the host locale;
    # decode leniently so the reader threads never die mid-stream.
    proc = subprocess.Popen(
        cmd, cwd=str(cwd), env=env, text=True, bufsize=1, encoding="utf-8", errors="replace",
        stdin=(subprocess.PIPE if stdin_data is not None else None),
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, **(popen_extra or {}))
    own_group = bool(popen_extra) and ("preexec_fn" in popen_extra or "start_new_session" in popen_extra)
    captured: dict = {"stdout": [], "stderr": []}
    total = {"n": 0}
    lock = threading.Lock()

    def _reader(name, pipe):
        try:
            for line in iter(pipe.readline, ""):
                with lock:
                    remaining = _EXEC_OUTPUT_CAP - total["n"]
                    if remaining <= 0:
                        continue  # keep draining (so the child doesn't block) but discard
                    piece = line[:remaining]  # cap mid-line so one huge print can't overflow
                    total["n"] += len(piece)
                    captured[name].append(piece)
                    cb = on_output
                if cb:
                    try:
                        cb(name, piece)
                    except Exception:
                        pass
        finally:
            try:
                pipe.close()
            except Exception:
                pass

    threads = [threading.Thread(target=_reader, args=(n, p), daemon=True)
               for n, p in (("stdout", proc.stdout), ("stderr", proc.stderr))]
    for t in threads:
        t.start()
    if stdin_data is not None:
        try:
            proc.stdin.write(stdin_data)
            proc.stdin.close()
        except Exception:
            pass
    timed_out = False
    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        _kill_proc(proc, own_group)
        try:
            proc.wait(timeout=5)
        except Exception:
            pass
    for t in threads:
        t.join(timeout=2)
    out = "".join(captured["stdout"])
    err = "".join(captured["stderr"])
    if total["n"] >= _EXEC_OUTPUT_CAP:
        err += "\n…[output truncated]…"
    return (proc.returncode if proc.returncode is not None else -1), out, err, timed_out


# P1-10: which image the docker engine runs. CODE_EXEC_IMAGE env wins; otherwise a
# locally built `ocd-sandbox:latest` (backend/sandbox/Dockerfile — pandas, matplotlib,
# openpyxl, python-docx, python-pptx, reportlab preinstalled, so "make me an xlsx"
# actually works offline) is preferred when present; else the stock slim image. The
# local-image probe runs once per process.
_SANDBOX_IMAGE_CACHE: dict = {"name": None}


def _sandbox_image() -> str:
    env = os.getenv("CODE_EXEC_IMAGE", "").strip()
    if env:
        return env
    if _SANDBOX_IMAGE_CACHE["name"] is None:
        import subprocess
        try:
            r = subprocess.run(["docker", "image", "inspect", "ocd-sandbox:latest"],
                               capture_output=True, timeout=10)
            _SANDBOX_IMAGE_CACHE["name"] = ("ocd-sandbox:latest" if r.returncode == 0
                                            else "python:3.11-slim")
        except Exception:  # noqa: BLE001 - no docker CLI etc.; the run will error anyway
            _SANDBOX_IMAGE_CACHE["name"] = "python:3.11-slim"
    return _SANDBOX_IMAGE_CACHE["name"]


def _run_docker(code: str, workdir: Path, on_output) -> tuple:
    cmd = ["docker", "run", "--rm", "-i", "--network", "none", "--memory", "512m",
           "--pids-limit", "128", "--cpus", "1", "-v", f"{workdir}:/w:rw", "-w", "/w",
           _sandbox_image(), "python", "-I", "-u", "-"]
    # Own session for the `docker run` CLI child so a timeout kill can't reach the backend.
    return _stream_subprocess(cmd, workdir, None, on_output, _EXEC_TIMEOUT_SEC,
                              stdin_data=code or "",
                              popen_extra=_isolation_popen_extra(local=False))


def _run_local(code: str, workdir: Path, on_output) -> tuple:
    import sys
    import tempfile
    scratch = workdir / ".exec"
    _ensure_dir(scratch)
    fd, script = tempfile.mkstemp(suffix=".py", dir=str(scratch))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(code or "")
        # -I isolated (ignore env/user site), -B no .pyc, -u unbuffered for live streaming.
        cmd = [sys.executable, "-I", "-B", "-u", script]
        return _stream_subprocess(cmd, workdir, _scrubbed_env(workdir), on_output,
                                  _EXEC_TIMEOUT_SEC,
                                  popen_extra=_isolation_popen_extra(local=True))
    finally:
        try:
            os.unlink(script)
        except OSError:
            pass


def execute_code(code: str, project: str | None = None, on_output=None) -> dict:
    """Execute Python for the `code_execution` tool. Runs in the project workspace so
    produced files persist. Returns a structured result:
    ``{ok, return_code, engine, stdout, stderr, timed_out, files:[{path,size,kind,text?}]}``.
    ``on_output(stream, text)`` streams output live. Never raises."""
    mode = _code_execution_mode()
    if mode == "off":
        return {"ok": False, "return_code": 126, "engine": "off", "stdout": "",
                "stderr": "Code execution is turned off in Settings.",
                "files": [], "timed_out": False}
    import shutil
    has_docker = bool(shutil.which("docker"))
    if mode in ("docker", "auto") and has_docker:
        engine = "docker"
    elif mode in ("local", "auto"):
        engine = "local"
    else:  # mode == "docker" and no docker available
        return {"ok": False, "return_code": 126, "engine": "docker-missing", "stdout": "",
                "stderr": ("Docker is required for 'docker' execution mode but was not found. "
                           "Install Docker Desktop, or set code execution to 'auto'/'local' "
                           "in Settings."),
                "files": [], "timed_out": False}
    root = _exec_workdir(project)
    before = _snapshot(root)
    runner = _run_docker if engine == "docker" else _run_local
    try:
        rc, out, err, timed = runner(code, root, on_output)
    except FileNotFoundError as e:
        return {"ok": False, "return_code": 127, "engine": engine, "stdout": "",
                "stderr": f"Execution engine unavailable: {str(e)[:200]}",
                "files": [], "timed_out": False}
    except Exception as e:  # noqa: BLE001 - surface any launch failure as a clean result
        return {"ok": False, "return_code": 1, "engine": engine, "stdout": "",
                "stderr": str(e)[:300], "files": [], "timed_out": False}
    files = _produced_files(before, root)
    return {"ok": (rc == 0 and not timed), "return_code": rc, "engine": engine,
            "stdout": out, "stderr": err, "files": files, "timed_out": timed}


def format_execution_result(res: dict) -> str:
    """Render an execute_code result as the text the model reads back (return code,
    captured output, and the list of files produced so it can reference them)."""
    if res["engine"] in ("off", "docker-missing"):
        return res["stderr"]
    lines = [f"return_code: {res['return_code']} (engine: {res['engine']})"]
    if res.get("timed_out"):
        lines.append(f"TIMED OUT after {_EXEC_TIMEOUT_SEC}s.")
    lines.append("--- stdout ---\n" + _cap(res.get("stdout", ""), 16000))
    if res.get("stderr"):
        lines.append("--- stderr ---\n" + _cap(res.get("stderr", ""), 8000))
    if res.get("files"):
        listing = "\n".join(f"- {f['path']} ({f['kind']}, {f['size']} bytes)"
                            for f in res["files"])
        lines.append("--- files produced (saved in the workspace, shown to the user) ---\n"
                     + listing)
    return "\n".join(lines)


def run_python(code: str) -> str:
    """Back-compat string wrapper around execute_code: runs in the general workspace and
    returns the formatted return_code/stdout/stderr text (no streaming, no file list)."""
    return format_execution_result(execute_code(code, None))


# ---- bash (default OFF, allowlisted + cwd-jailed) ---- #
def run_bash(command: str, restart: bool = False) -> str:
    import shlex
    import subprocess
    _ensure_dir(SANDBOX_ROOT)
    if restart:
        return "Bash session restarted."
    command = (command or "").strip()
    if not command:
        return "Rejected: empty command."
    if any(tok in command for tok in ("&&", "||", "|", ";", "&", ">", "<", "`",
                                      "$(", "${", "..", "\n")):
        return ("Rejected: pipes, redirects, chaining, and path traversal are not "
                "allowed in the sandbox. Run one simple allowlisted command.")
    try:
        parts = shlex.split(command)
    except Exception:
        return "Rejected: could not parse command."
    if not parts or parts[0] not in _BASH_ALLOW:
        return (f"Rejected: '{parts[0] if parts else ''}' is not allowlisted. Allowed: "
                + ", ".join(sorted(_BASH_ALLOW)))
    # C2: no argument may point outside the sandbox (blocks absolute-path reads
    # like `cat /etc/passwd` that the metacharacter/`..` filter did not catch).
    escaping = next((a for a in parts[1:] if _bash_arg_escapes_jail(a)), None)
    if escaping is not None:
        return ("Rejected: argument outside the sandbox is not allowed "
                f"('{escaping}'). Only paths inside the session workspace are permitted.")
    try:
        proc = subprocess.run(parts, cwd=str(SANDBOX_ROOT), capture_output=True,
                              text=True, timeout=30, shell=False)
        out = (proc.stdout or "") + (proc.stderr or "")
        return _scrub_secrets(_cap(out, 16000)) or "(no output)"
    except subprocess.TimeoutExpired:
        return "Timed out after 30s."
    except FileNotFoundError:
        return f"Rejected: '{parts[0]}' is not available on this system."
    except Exception as e:
        return f"Error: {str(e)[:200]}"


# ---- shared path jail for text_editor / memory ---- #
def _jail_path(root: Path, path: str) -> Path | None:
    _ensure_dir(root)
    raw = (path or "").strip().replace("\\", "/").lstrip("/")
    for prefix in ("memories/", "workspace/"):
        if raw.startswith(prefix):
            raw = raw[len(prefix):]
    if raw in ("memories", "workspace"):
        raw = ""
    try:
        target = (root / raw).resolve()
        target.relative_to(root.resolve())
        return target
    except Exception:
        return None


# ---- text_editor (str_replace_based_edit_tool; default OFF, workspace-jailed) ---- #
def text_editor(args: dict, root: Path) -> str:
    cmd = args.get("command", "")
    target = _jail_path(root, args.get("path", ""))
    if target is None:
        return "Error: path is outside the workspace."
    if cmd == "view":
        if target.is_dir():
            items = sorted((p.name + ("/" if p.is_dir() else ""))
                           for p in target.iterdir())
            return (f"Directory {args.get('path')}:\n" + "\n".join(items)
                    if items else "(empty directory)")
        if not target.exists():
            return "Error: File not found"
        lines = target.read_text(encoding="utf-8", errors="replace").splitlines()
        start, end = 1, len(lines)
        vr = args.get("view_range")
        if isinstance(vr, list) and len(vr) == 2:
            start = max(1, int(vr[0]))
            end = len(lines) if vr[1] in (-1, None) else int(vr[1])
        body = "\n".join(f"{i}: {lines[i-1]}"
                         for i in range(start, min(end, len(lines)) + 1))
        return body[:24000] or "(empty file)"
    if cmd == "create":
        _ensure_dir(target.parent)
        target.write_text(args.get("file_text", "") or "", encoding="utf-8")
        return f"File created successfully at: {args.get('path')}"
    if cmd == "str_replace":
        if not target.exists():
            return "Error: File not found"
        content = target.read_text(encoding="utf-8", errors="replace")
        old = args.get("old_str", "") or ""
        n = content.count(old) if old else 0
        if n == 0:
            return "Error: No match found for replacement."
        if n > 1:
            return f"Error: Found {n} matches for old_str; it must be unique."
        target.write_text(content.replace(old, args.get("new_str", "") or "", 1),
                          encoding="utf-8")
        return "Successfully replaced text at exactly one location."
    if cmd == "insert":
        if not target.exists():
            return "Error: File not found"
        lines = target.read_text(encoding="utf-8", errors="replace").splitlines()
        idx = max(0, min(int(args.get("insert_line", 0) or 0), len(lines)))
        ins = args.get("insert_text", args.get("new_str", "")) or ""
        lines[idx:idx] = ins.splitlines() or [ins]
        target.write_text("\n".join(lines), encoding="utf-8")
        return f"The file {args.get('path')} has been edited."
    return f"Error: unknown command '{cmd}'."


# ---- memory (persistent /memories; default OFF, path-jailed) ---- #
def memory_tool(args: dict, root: Path) -> str:
    cmd = args.get("command", "")
    _ensure_dir(root)
    miss = "The path {} does not exist. Please provide a valid path."
    if cmd == "rename":
        src = _jail_path(root, args.get("old_path", ""))
        dst = _jail_path(root, args.get("new_path", ""))
        if src is None or dst is None or not src.exists():
            return miss.format(args.get("old_path"))
        _ensure_dir(dst.parent)
        src.rename(dst)
        return f"Successfully renamed {args.get('old_path')} to {args.get('new_path')}"
    target = _jail_path(root, args.get("path", ""))
    if target is None:
        return "Error: path is outside /memories."
    if cmd == "view":
        path = (args.get("path") or "/memories")
        if target.is_dir() or path.rstrip("/") in ("", "/memories"):
            base = target if target.exists() and target.is_dir() else root
            rows = [f"{p.stat().st_size}\t/memories/{p.relative_to(root).as_posix()}"
                    for p in sorted(base.rglob("*")) if p.is_file()]
            listing = "\n".join(rows) if rows else "(no memory files yet)"
            return (f"Here're the files and directories up to 2 levels deep in "
                    f"{path}:\n{listing}")
        if not target.exists():
            return miss.format(args.get("path"))
        lines = target.read_text(encoding="utf-8", errors="replace").splitlines()
        body = "\n".join(f"{i:>6}\t{lines[i-1]}" for i in range(1, len(lines) + 1))
        return f"Here's the content of {args.get('path')} with line numbers:\n{body}"[:24000]
    if cmd == "create":
        _ensure_dir(target.parent)
        target.write_text(args.get("file_text", "") or "", encoding="utf-8")
        return f"File created successfully at: {args.get('path')}"
    if cmd == "str_replace":
        if not target.exists():
            return miss.format(args.get("path"))
        content = target.read_text(encoding="utf-8", errors="replace")
        old = args.get("old_str", "") or ""
        if old and content.count(old) == 1:
            target.write_text(content.replace(old, args.get("new_str", "") or "", 1),
                              encoding="utf-8")
            return "The memory file has been edited."
        return "Error: old_str must match exactly one location."
    if cmd == "insert":
        if not target.exists():
            return miss.format(args.get("path"))
        lines = target.read_text(encoding="utf-8", errors="replace").splitlines()
        idx = max(0, min(int(args.get("insert_line", 0) or 0), len(lines)))
        ins = args.get("insert_text", args.get("new_str", "")) or ""
        lines[idx:idx] = ins.splitlines() or [ins]
        target.write_text("\n".join(lines), encoding="utf-8")
        return f"The file {args.get('path')} has been edited."
    if cmd == "delete":
        if not target.exists():
            return miss.format(args.get("path"))
        target.unlink()
        return f"Successfully deleted {args.get('path')}"
    return f"Error: unknown command '{cmd}'."


# --------------------------------------------------------------------------- #
#  GitHub import — public repo text files into a project's KB
# --------------------------------------------------------------------------- #
_GH_API = "https://api.github.com"
_TEXT_SUFFIXES = {".md", ".txt", ".sql", ".py", ".json", ".yaml", ".yml",
                  ".csv", ".js", ".ts", ".toml", ".cfg", ".ini", ".rst"}
_GH_MAX_FILES = 40
_GH_MAX_BYTES = 200_000


def _parse_repo(url: str):
    url = (url or "").strip().rstrip("/")
    m = re.search(r"github\.com[:/]+([^/]+)/([^/]+?)(?:\.git)?$", url)
    if m:
        return m.group(1), m.group(2)
    parts = url.split("/")
    if len(parts) == 2:
        return parts[0], parts[1]
    return None, None


def import_github_repo(repo_url: str, project_id: str) -> tuple[int, str]:
    """Fetch a public repo's text files and ingest them into the project KB.

    Returns (files_ingested, error_message). error is "" on success.
    """
    owner, repo = _parse_repo(repo_url)
    if not owner or not repo:
        return 0, "Could not parse a github owner/repo from that URL."
    try:
        import httpx
        with httpx.Client(timeout=30, headers={"User-Agent": _UA,
                          "Accept": "application/vnd.github+json"}) as client:
            info = client.get(f"{_GH_API}/repos/{owner}/{repo}")
            if info.status_code != 200:
                return 0, f"Repo not found or private ({info.status_code})."
            branch = info.json().get("default_branch", "main")
            tree = client.get(
                f"{_GH_API}/repos/{owner}/{repo}/git/trees/{branch}?recursive=1")
            if tree.status_code != 200:
                return 0, f"Could not list files ({tree.status_code})."
            items = tree.json().get("tree", [])
            paths = [it["path"] for it in items
                     if it.get("type") == "blob"
                     and Path(it["path"]).suffix.lower() in _TEXT_SUFFIXES
                     and it.get("size", 0) <= _GH_MAX_BYTES][:_GH_MAX_FILES]

            kb_dir = config.PROJECTS_DIR / project_id / "knowledge"
            kb_dir.mkdir(parents=True, exist_ok=True)
            count = 0
            for path in paths:
                raw = client.get(
                    f"https://raw.githubusercontent.com/{owner}/{repo}/{branch}/{path}")
                if raw.status_code != 200:
                    continue
                safe = f"gh_{owner}_{repo}_" + path.replace("/", "_")
                dest = kb_dir / safe[:180]
                try:
                    dest.write_text(raw.text, encoding="utf-8")
                    knowledge.ingest_file_to_kb(project_id, dest)
                    count += 1
                except Exception:
                    continue
        return count, ""
    except Exception as e:
        return 0, str(e)[:160]
