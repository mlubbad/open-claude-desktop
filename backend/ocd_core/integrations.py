"""
Integrations domain layer — Skills, GitHub import, Connectors, Web search.

UI-agnostic. Everything here is plain sync Python (callers wrap blocking work in
asyncio.to_thread). Keeps the composer's "+" menu features out of core.py.
"""
from __future__ import annotations

import os
import re
import json
from pathlib import Path

from . import config
from . import bigquery
from . import chroma
from . import knowledge
from . import llm
from . import mcp_registry

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
from .skills import (  # noqa: E402
    split_frontmatter as _split_frontmatter,
    list_skills,
    get_skill,
    matching_skill,
)


# --------------------------------------------------------------------------- #
#  Plugins runtime — load plugins/*.py exposing TOOL (schema) + run(args)
# --------------------------------------------------------------------------- #
PLUGINS_DIR = Path(os.getenv("PLUGINS_DIR", str(config.REPO_ROOT / "plugins")))


def _load_plugin_module(path: Path):
    import importlib.util
    try:
        spec = importlib.util.spec_from_file_location(
            f"plugin_{path.stem}", path)
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


# Connector auth tokens live OUTSIDE the git-tracked connectors.json, in a
# gitignored/dockerignored sidecar keyed by connector id, resolved at call time.
CONNECTOR_SECRETS_FILE = config.REPO_ROOT / ".connector_secrets.json"


def _load_connector_secrets() -> dict:
    if CONNECTOR_SECRETS_FILE.exists():
        try:
            d = json.loads(CONNECTOR_SECRETS_FILE.read_text(encoding="utf-8"))
            return d if isinstance(d, dict) else {}
        except Exception:
            return {}
    return {}


def _save_connector_secrets(d: dict) -> None:
    try:
        CONNECTOR_SECRETS_FILE.write_text(json.dumps(d, ensure_ascii=False, indent=2),
                                          encoding="utf-8")
    except Exception:
        pass


def _connector_secret(cid: str) -> str:
    """Auth-header value for a connector: the sidecar first, then any legacy inline
    value on the record (back-compat for connectors added before the sidecar)."""
    v = _load_connector_secrets().get(cid)
    if v:
        return v
    u = next((x for x in _load_user_connectors() if x["id"] == cid), None)
    return (u or {}).get("header_value", "") or ""


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", (text or "").lower()).strip("_") or "rest"


def add_connector(name: str, base_url: str, header_key: str = "",
                  header_value: str = "") -> dict:
    items = _load_user_connectors()
    cid = _slug(name)
    n, base = cid, cid
    i = 2
    while any(it["id"] == cid for it in items):
        cid = f"{base}_{i}"
        i += 1
    item = {"id": cid, "name": name.strip() or cid, "type": "rest",
            "base_url": base_url.strip().rstrip("/"),
            "header_key": header_key.strip()}
    items.append(item)
    _save_user_connectors(items)
    if header_value.strip():  # secret -> gitignored sidecar, never connectors.json
        secrets = _load_connector_secrets()
        secrets[cid] = header_value.strip()
        _save_connector_secrets(secrets)
    return item


def remove_connector(cid: str):
    _save_user_connectors([i for i in _load_user_connectors() if i["id"] != cid])
    secrets = _load_connector_secrets()
    if secrets.pop(cid, None) is not None:
        _save_connector_secrets(secrets)


def _http_get(url: str, headers: dict, timeout: int = 15):
    """SSRF-guarded GET for user REST connectors: http/https only, private/internal
    hosts blocked before the request and re-checked after redirects (parity with
    web_fetch). Raises ValueError on a disallowed URL/host."""
    from urllib.parse import urlparse

    import httpx
    p = urlparse((url or "").strip())
    if p.scheme not in ("http", "https") or not p.netloc:
        raise ValueError("connector url must be http(s)")
    if _blocked_host(p.hostname or ""):
        raise ValueError("blocked host (private/internal address)")
    r = httpx.get(url, headers=headers, timeout=timeout, follow_redirects=True)
    final = urlparse(str(r.url)).hostname or ""
    if final and final != (p.hostname or "") and _blocked_host(final):
        raise ValueError("redirected to blocked host")
    return r


def test_connector(cid: str) -> str:
    u = next((x for x in _load_user_connectors() if x["id"] == cid), None)
    if not u:
        return "Connector not found."
    headers = {"User-Agent": _UA}
    if u.get("header_key"):
        headers[u["header_key"]] = _connector_secret(cid)
    try:
        r = _http_get(u["base_url"], headers)
        return f"OK — HTTP {r.status_code} from {u['base_url']}"
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
        headers[u["header_key"]] = _connector_secret(cid)
    try:
        r = _http_get(url, headers, timeout=20)
        return f"HTTP {r.status_code} {url}\n{r.text[:3000]}"
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


def _resolve_cfg(cfg: dict) -> dict:
    """Resolve portable placeholders (${PYTHON}, ${REPO_ROOT}) in an MCP server
    cfg at call time, so mcp_servers.json never stores machine-absolute paths."""
    import sys
    repl = {"${PYTHON}": sys.executable, "${REPO_ROOT}": str(config.REPO_ROOT)}

    def _sub(s):
        if isinstance(s, str):
            for k, v in repl.items():
                s = s.replace(k, v)
        return s

    out = dict(cfg)
    out["command"] = _sub(cfg.get("command", ""))
    out["args"] = [_sub(a) for a in cfg.get("args", [])]
    return out


def add_mcp_server(name: str, command: str, args: list[str] | None = None) -> dict:
    """Register an MCP (stdio) server and cache its tool specs. Discovery happens
    now so the agent tool list can be assembled synchronously later."""
    args = args or []
    sid = _slug(name)
    items = [s for s in _load_mcp_servers() if s["id"] != sid]
    item = {"id": sid, "name": name.strip() or sid, "transport": "stdio",
            "command": command.strip(), "args": args}
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


def remove_mcp_server(sid: str):
    items = _load_mcp_servers()
    for s in items:
        if s["id"] == sid:
            mcp_registry.registry.drop(_resolve_cfg(s))  # terminate the persistent subprocess
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


def list_mcp_servers() -> list[dict]:
    """Registered MCP servers (without the verbose cached tool schemas)."""
    return [{"id": s["id"], "name": s["name"], "transport": s.get("transport", "stdio"),
             "command": s.get("command", ""), "args": s.get("args", []),
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
    from urllib.parse import urlparse, parse_qs, unquote
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
        lines = [re.sub(r"^[\-\d\.\)\s•]+", "", l).strip()
                 for l in (resp.choices[0].message.content or "").splitlines()]
        subs = [l for l in lines if l][:n]
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
# Absolute paths would let an allowlisted reader (cat/find/ls/dir/...) escape the
# sandbox cwd: POSIX "/...", home "~...", Windows drive "C:\..."/"C:/...", or UNC
# "\\host". Matched at a token boundary so mid-token slashes (subdir/, https://)
# and grep patterns are unaffected. Combined with the ".." block => confined to
# the sandbox working directory.
_ABS_PATH_RE = re.compile(r"(^|\s)([/~]|[A-Za-z]:[\\/]|\\\\)")


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
    import socket
    import ipaddress
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
    from urllib.parse import urlparse
    import time as _t
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
    import subprocess
    import sys
    import shutil
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
    import subprocess
    import shlex
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
    if _ABS_PATH_RE.search(command):
        return ("Rejected: absolute paths are not allowed in the sandbox. Use paths "
                "relative to the sandbox working directory.")
    try:
        parts = shlex.split(command)
    except Exception:
        return "Rejected: could not parse command."
    if not parts or parts[0] not in _BASH_ALLOW:
        return (f"Rejected: '{parts[0] if parts else ''}' is not allowlisted. Allowed: "
                + ", ".join(sorted(_BASH_ALLOW)))
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
def _jail_path(root: Path, path: str) -> "Path | None":
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
