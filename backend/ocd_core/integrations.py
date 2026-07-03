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
from pathlib import Path

from . import bigquery, chroma, config, knowledge, llm, mcp_registry

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


def _load_plugin_module(path: Path):
    import importlib.util
    try:
        spec = importlib.util.spec_from_file_location(
            f"aj360_plugin_{path.stem}", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)  # type: ignore[union-attr]
        return mod
    except Exception:
        return None


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
    if CONNECTORS_FILE.exists():
        try:
            d = json.loads(CONNECTORS_FILE.read_text(encoding="utf-8"))
            return d if isinstance(d, list) else []
        except Exception:
            return []
    return []


def _save_user_connectors(items: list[dict]):
    try:
        CONNECTORS_FILE.write_text(json.dumps(items, ensure_ascii=False, indent=2),
                                   encoding="utf-8")
    except Exception:
        pass


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


def _load_mcp_servers() -> list[dict]:
    if MCP_FILE.exists():
        try:
            d = json.loads(MCP_FILE.read_text(encoding="utf-8"))
            return d if isinstance(d, list) else []
        except Exception:
            return []
    return []


def _save_mcp_servers(items: list[dict]):
    try:
        MCP_FILE.write_text(json.dumps(items, ensure_ascii=False, indent=2),
                            encoding="utf-8")
    except Exception:
        pass


# NOTE: the per-call spawn helpers (_run_async / _mcp_session /
# _mcp_discover_async / _mcp_call_async) were removed in favor of the
# single-spawn mcp_registry, which keeps ONE persistent ClientSession per
# server (reused across calls) with per-call timeouts and clean shutdown.


def _mcp_auth_key(sid: str) -> str:
    return f"mcp:{sid}:auth_token"


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
    else:
        out["command"] = _sub(cfg.get("command", ""))
        out["args"] = [_sub(a) for a in cfg.get("args", [])]
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
        item["tools"] = mcp_registry.registry.discover(_resolve_cfg(item))
        item["status"] = "connected"
        item["detail"] = f"{len(item['tools'])} tools"
    except Exception as e:
        item["tools"] = []
        item["status"] = "error"
        item["detail"] = str(e)[:140]
    items.append(item)
    _save_mcp_servers(items)
    return item


def add_demo_mcp_server() -> dict:
    """Register the bundled demo MCP server (mcp_servers/demo_server.py) using the
    current Python interpreter — no node, no network, no secrets."""
    return add_mcp_server("AJ360 Demo", "${PYTHON}",
                          ["${REPO_ROOT}/mcp_servers/demo_server.py"])


def remove_mcp_server(sid: str):
    items = _load_mcp_servers()
    for s in items:
        if s["id"] == sid:
            mcp_registry.registry.drop(_resolve_cfg(s))  # terminate the persistent session
            if s.get("auth"):
                from . import secrets
                with contextlib.suppress(Exception):
                    secrets.get_secret_store().delete(_mcp_auth_key(sid))
    _save_mcp_servers([s for s in items if s["id"] != sid])


def refresh_mcp_server(sid: str) -> dict:
    items = _load_mcp_servers()
    for s in items:
        if s["id"] == sid:
            try:
                mcp_registry.registry.drop(_resolve_cfg(s))  # respawn with fresh state
                s["tools"] = mcp_registry.registry.discover(_resolve_cfg(s))
                s["status"] = "connected"
                s["detail"] = f"{len(s['tools'])} tools"
            except Exception as e:
                s["status"] = "error"
                s["detail"] = str(e)[:140]
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


def list_mcp_servers() -> list[dict]:
    """Registered MCP servers (without the verbose cached tool schemas)."""
    return [{"id": s["id"], "name": s["name"], "transport": s.get("transport", "stdio"),
             "command": s.get("command", ""), "args": s.get("args", []),
             "url": s.get("url", ""), "auth": bool(s.get("auth")),
             "status": s.get("status", "unknown"), "detail": s.get("detail", ""),
             "tool_count": len(s.get("tools", []))}
            for s in _load_mcp_servers()]


def mcp_tools(enabled_ids: list[str]) -> list[dict]:
    """Agent tool specs for the enabled MCP servers, named mcp_<sid>_<tool>."""
    out: list[dict] = []
    for s in _load_mcp_servers():
        if s["id"] not in enabled_ids:
            continue
        for t in s.get("tools", []):
            out.append({"type": "function", "function": {
                "name": f"mcp_{s['id']}_{t['name']}",
                "description": (t.get("description")
                               or f"{s['name']} · {t['name']}")[:1000],
                "parameters": t.get("inputSchema") or {"type": "object",
                                                        "properties": {}}}})
    return out


def call_mcp(full_name: str, args: dict) -> str:
    for s in _load_mcp_servers():
        prefix = f"mcp_{s['id']}_"
        if full_name.startswith(prefix):
            tool = full_name[len(prefix):]
            if any(t["name"] == tool for t in s.get("tools", [])):
                try:
                    return mcp_registry.registry.call(_resolve_cfg(s), tool, args or {})
                except Exception as e:
                    return f"MCP '{s['id']}' call failed: {str(e)[:200]}"
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
#  Web search — keyless DuckDuckGo HTML endpoint
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


def _web_results(query: str, n: int = 5) -> list[dict]:
    """Structured web results: list of {title, url, snippet, domain, favicon}."""
    query = (query or "").strip()
    if not query:
        return []
    try:
        import httpx
        resp = httpx.post(_DDG_URL, data={"q": query}, timeout=15,
                          headers={"User-Agent": _UA})
        html = resp.text
    except Exception:
        return []
    out: list[dict] = []
    for m in re.finditer(
            r'result__a"[^>]*href="(.*?)".*?>(.*?)</a>.*?'
            r'result__snippet"[^>]*>(.*?)</a>', html, re.DOTALL):
        url, title, snippet = m.group(1), m.group(2), m.group(3)
        title = re.sub(r"<.*?>", "", title).strip()
        snippet = re.sub(r"<.*?>", "", snippet).strip()
        url = _clean_ddg_url(re.sub(r"<.*?>", "", url).strip())
        dom = _domain(url)
        if title and url:
            out.append({"title": title, "url": url, "snippet": snippet,
                        "domain": dom,
                        "favicon": (f"https://www.google.com/s2/favicons?domain={dom}&sz=64"
                                    if dom else "")})
        if len(out) >= n:
            break
    return out


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
    s = re.sub(r"(?is)<(script|style|head|nav|footer|svg)[^>]*>.*?</\1>", " ", html_src)
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


# ---- code_execution (default OFF, sandboxed) ---- #
def run_python(code: str) -> str:
    """Run a Python snippet in a best-effort sandbox: Docker --network none if
    available, else `python -I` in an ephemeral temp dir with a scrubbed env +
    30s timeout. Returns return_code/stdout/stderr (Windows: reduced isolation)."""
    import shutil
    import subprocess
    import tempfile
    _ensure_dir(SANDBOX_ROOT)
    workdir = tempfile.mkdtemp(prefix="code_", dir=str(SANDBOX_ROOT))
    try:
        if not shutil.which("docker"):
            # C3: do NOT fall back to host execution. `python -I` does not sandbox the
            # filesystem/network/OS — running model-written code on the host is RCE.
            return ("code_execution disabled: a container runtime (Docker) is required "
                    "for isolated execution. Refusing to run model-written code on the host.")
        cmd = ["docker", "run", "--rm", "--network", "none", "--memory", "512m",
               "--pids-limit", "64", "--cpus", "1", "-v", f"{workdir}:/w:rw",
               "-w", "/w", "python:3.11-slim", "python", "-I", "-c", code or ""]
        proc = subprocess.run(cmd, cwd=workdir, env=None, capture_output=True,
                              text=True, timeout=30)
        return (f"return_code: {proc.returncode}\n--- stdout ---\n"
                f"{_cap(proc.stdout, 16000)}\n--- stderr ---\n{_cap(proc.stderr, 8000)}")
    except subprocess.TimeoutExpired:
        return "return_code: 124\n--- stderr ---\nTimed out after 30s."
    except Exception as e:
        return f"return_code: 1\n--- stderr ---\n{str(e)[:300]}"
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


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
