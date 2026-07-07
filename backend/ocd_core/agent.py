"""
Open Claude Desktop BigQuery agent — UI-agnostic orchestration layer.

`run_turn` is an async generator that drives the GLM tool-calling loop and
*yields structured events* describing what is happening. Any presentation layer
(Reflex, Chainlit, CLI) can consume the stream and render it however it likes —
the agent knows nothing about the UI.

Event shapes (all dicts with a "type"). These are what `run_turn` actually
yields; the API layer appends a terminal {"type": "done"} after the stream ends.

  Thinking / answer framing (panel open/close + region switching):
  {"type": "think_open",      "phase": str}                  # phase "plan"|"verify"
  {"type": "think_close",     "elapsed": int}                # seconds spent thinking
  {"type": "answer_open"}                                    # begin the answer region
  {"type": "answer_to_think", "phase": str, "elapsed": int}  # fold a stray bit back
                                                             #   into the think panel

  Streamed text (token deltas):
  {"type": "delta", "scope": str, "text": str}               # scope "answer"|"think"

  Tool lifecycle (all carry "id" = the tool_call_id):
  {"type": "tool",        "id": str, "name": str, "input": str,
                          "label_running": str, "label_done": str, "icon": str}
  {"type": "tool_result", "id": str, "name": str, "summary": str}   # non-table output
  {"type": "tool_error",  "id": str, "name": str, "text": str}      # tool failed
  {"type": "table",       "id": str, "columns": list, "rows": list, # SELECT result
                          "total": int, "bytes": int}
  {"type": "sources",     "id": str, "items": list}          # web/research citations

  Artifacts (renderable side-panel documents; derived from an artifact tool call):
  {"type": "artifact_open",  "id": str, "title": str, "kind": str, "language": str}
  {"type": "artifact_delta", "id": str, "text": str}
  {"type": "artifact_close", "id": str, "version": int}

  Usage (emitted once at the end of a successful turn — drives the context/cost meter):
  {"type": "usage", "model": str, "context_tokens": int, "output_tokens": int,
                    "context_limit": int, "context_pct": int, "cost_usd": float|None}

  Interactive permission (HITL — only when a turn_id + non-auto permission mode):
  {"type": "approval_required", "turn_id": str, "id": str,   # awaiting a decision;
                          "name": str, "input": str}         #   reply via the API

  Failure:
  {"type": "error", "text": str}                             # the turn could not proceed

Effort levels (Low/Medium/High/Max) control the depth of multi-turn thinking:
  Low/Medium — direct tool loop, no extra reasoning passes.
  High       — a planning pass before acting.
  Max        — planning pass + a self-verification pass before the final answer.
"""
from __future__ import annotations

import asyncio
import json
import re
import time
import types

from . import (
    artifact_stream,
    artifact_tools,
    bigquery,
    bigquery_tools,
    config,
    context,
    permissions,
    prompts,
    schema_catalog,
    usage,
    util,
)
from .llm import LLMConfigError, reasoning_of, resolve_turn_client

WEB_SEARCH_TOOL = {"type": "function", "function": {
    "name": "web_search",
    "description": "Search the public web for current information not available in BigQuery "
                   "(industry benchmarks, definitions, recent events).",
    "parameters": {"type": "object", "properties": {
        "query": {"type": "string", "description": "The search query."}},
        "required": ["query"]}}}

RESEARCH_TOOL = {"type": "function", "function": {
    "name": "deep_research",
    "description": "Run PARALLEL multi-source web research on a topic: expands it into "
                   "several distinct search angles, searches them concurrently, and "
                   "returns combined findings. Use ONCE for a broad/open question, then "
                   "synthesize a cited answer from the results.",
    "parameters": {"type": "object", "properties": {
        "topic": {"type": "string", "description": "The research topic / question."}},
        "required": ["topic"]}}}

# ---- Claude-equivalent built-in tools (mirror Claude's names + input schemas) ----
WEB_FETCH_TOOL = {"type": "function", "function": {
    "name": "web_fetch",
    "description": "Fetch the full text of ONE web page by URL (e.g. a result from "
                   "web_search) and return its cleaned text. Use to read a specific page.",
    "parameters": {"type": "object", "properties": {
        "url": {"type": "string",
                "description": "The http/https URL to fetch (max 250 chars)."}},
        "required": ["url"]}}}

CODE_EXECUTION_TOOL = {"type": "function", "function": {
    "name": "code_execution",
    "description": "Run a short Python 3 snippet in a sandbox (no network, 30s limit) and "
                   "return stdout/stderr. Use for ad-hoc computation, data shaping, and "
                   "verifying numbers. Use print(...) to produce output.",
    "parameters": {"type": "object", "properties": {
        "code": {"type": "string", "description": "Python source to execute."}},
        "required": ["code"]}}}

BASH_TOOL = {"type": "function", "function": {
    "name": "bash",
    "description": "Run ONE allowlisted shell command (ls, cat, grep, find, head, tail, "
                   "wc, echo, pwd, python, sort, uniq, cut …) in a confined sandbox "
                   "directory. No pipes, redirects, or command chaining.",
    "parameters": {"type": "object", "properties": {
        "command": {"type": "string", "description": "The shell command to run."},
        "restart": {"type": "boolean", "description": "Restart the sandbox session."}},
        "required": []}}}

TEXT_EDITOR_TOOL = {"type": "function", "function": {
    "name": "text_editor",
    "description": "View and edit files in the workspace using the str_replace protocol. "
                   "command=view reads a file/dir; create makes a new file; str_replace "
                   "replaces a UNIQUE snippet; insert adds text at a line.",
    "parameters": {"type": "object", "properties": {
        "command": {"type": "string",
                    "enum": ["view", "create", "str_replace", "insert"]},
        "path": {"type": "string", "description": "Workspace-relative file path."},
        "file_text": {"type": "string", "description": "Full contents for create."},
        "old_str": {"type": "string", "description": "Exact unique text to replace."},
        "new_str": {"type": "string", "description": "Replacement text."},
        "insert_line": {"type": "integer", "description": "Insert after this line."},
        "insert_text": {"type": "string", "description": "Text to insert."},
        "view_range": {"type": "array", "items": {"type": "integer"},
                       "description": "[start, end] lines for view."}},
        "required": ["command", "path"]}}}

TASK_TOOL = {"type": "function", "function": {
    "name": "spawn_subagent",
    "description": "Delegate a well-scoped subtask to an autonomous subagent that runs in its "
                   "OWN fresh context and reports back a single concise result. Use it for work "
                   "that would otherwise flood your context (reading many files, multi-step "
                   "research, isolated analysis) or that benefits from a clean slate. The "
                   "subagent has the SAME tools you do (except it cannot spawn further "
                   "subagents) but CANNOT see this conversation and CANNOT ask questions — give "
                   "it a complete, self-contained prompt stating all needed context and exactly "
                   "what to return. Prefer one subagent per independent subtask.",
    "parameters": {"type": "object", "properties": {
        "description": {"type": "string",
                        "description": "A 3-6 word label for the subtask (shown in the UI)."},
        "prompt": {"type": "string",
                   "description": "The full, self-contained instruction for the subagent, "
                                  "including all context it needs and exactly what to return."}},
        "required": ["description", "prompt"]}}}

PLAN_TOOL = {"type": "function", "function": {
    "name": "exit_plan_mode",
    "description": "Call this ONLY in plan mode, once you have a complete, concrete plan. "
                   "Presents the plan to the user for approval; on approval you leave plan "
                   "mode and may implement it. Do NOT call it to ask a question or before you "
                   "have finished researching — investigate read-only first.",
    "parameters": {"type": "object", "properties": {
        "plan": {"type": "string",
                 "description": "The plan to carry out, as concise Markdown (steps / files "
                                "to change / what will be verified)."}},
        "required": ["plan"]}}}

MEMORY_TOOL = {"type": "function", "function": {
    "name": "memory",
    "description": "Persistent cross-conversation memory under /memories. Commands: view, "
                   "create, str_replace, insert, delete, rename. ALWAYS `view /memories` "
                   "at the start of a task to recover prior context.",
    "parameters": {"type": "object", "properties": {
        "command": {"type": "string",
                    "enum": ["view", "create", "str_replace", "insert", "delete", "rename"]},
        "path": {"type": "string", "description": "Path under /memories."},
        "file_text": {"type": "string"}, "old_str": {"type": "string"},
        "new_str": {"type": "string"}, "insert_line": {"type": "integer"},
        "insert_text": {"type": "string"}, "old_path": {"type": "string"},
        "new_path": {"type": "string"},
        "view_range": {"type": "array", "items": {"type": "integer"}}},
        "required": ["command"]}}}

PLAN_MODE_SECTION = (
    "## Plan mode\n"
    "You are in PLAN MODE. Investigate the task using READ-ONLY tools only (searching, "
    "fetching, reading files). You MUST NOT modify files, run shell commands, execute "
    "code, run SQL, or change any state yet — those tools are blocked. When you have a "
    "concrete, complete plan, call the `exit_plan_mode` tool with the plan as Markdown so "
    "the user can approve it; only after approval may you make changes. If the task is a "
    "plain question that needs no changes, answer it directly instead of planning."
)

# Effort -> behaviour. `steps` is the tool-loop iteration cap; `plan`/`verify` add
# explicit thinking passes; `temp` raises exploration at higher effort.
EFFORT = {
    "Low":    {"steps": 3,  "plan": False, "verify": False, "temp": 0.0},
    "Medium": {"steps": 7,  "plan": False, "verify": False, "temp": 0.1},
    "High":   {"steps": 11, "plan": True,  "verify": False, "temp": 0.2},
    "Extra":  {"steps": 13, "plan": True,  "verify": False, "temp": 0.25},
    "Max":    {"steps": 16, "plan": True,  "verify": True,  "temp": 0.3},
}

# The system prompt is composed by ocd_core.prompts (domain-agnostic base + opt-in
# sections). The BigQuery/AJ360 guidance is contributed by bigquery_tools only when
# that connector is enabled — the agent core no longer hard-codes any domain.


_LABEL_RE = re.compile(
    r"^\s*(?:#{1,6}\s*)?(?:\*\*)?\s*"
    r"(?:corrected|final|verified|revised|improved)\s+answer\s*(?:\*\*)?\s*:?\s*\n+",
    re.IGNORECASE)


def _strip_answer_label(text: str) -> str:
    """Drop a leading 'Corrected Answer'/'Final Answer' heading the verify pass may
    still emit, so the refined answer reads as a seamless replacement."""
    return _LABEL_RE.sub("", text, count=1).lstrip()


# Transient failures worth retrying before giving up on a model (rate limits, upstream
# hiccups, timeouts). Permanent ones (bad request, auth) fall through immediately.
_RETRYABLE_STATUS = frozenset({408, 409, 425, 429, 500, 502, 503, 504})
_RETRYABLE_NAME_HINTS = ("ratelimit", "timeout", "connection", "internalserver",
                         "serviceunavailable", "apiconnection", "overloaded")


def _is_retryable(exc: BaseException) -> bool:
    """Whether an LLM call error is transient and worth a backoff retry."""
    status = getattr(exc, "status_code", None)
    if not isinstance(status, int):
        status = getattr(exc, "status", None)
    if isinstance(status, int) and status in _RETRYABLE_STATUS:
        return True
    name = type(exc).__name__.lower()
    return any(h in name for h in _RETRYABLE_NAME_HINTS)


async def _create_with_retry(llm, model, kw, retries: int = 2, base_delay: float = 0.5):
    """Call the model, retrying transient errors with exponential backoff. Non-transient
    errors (and the final attempt) raise so the caller can fall back."""
    delay = base_delay
    for attempt in range(retries + 1):
        try:
            return await asyncio.to_thread(llm.chat.completions.create, model=model, **kw)
        except Exception as e:
            if attempt < retries and _is_retryable(e):
                await asyncio.sleep(delay)
                delay *= 2
                continue
            raise


async def _llm_create(llm, model, messages, tools=None, temperature=0.1,
                      max_tokens=4096, fallback_model=None):
    """LLM create with transient-error retry, then a single fallback to `fallback_model`.

    Transient errors (rate limits, timeouts, 5xx) are retried with backoff on the chosen
    model first; only if that is exhausted (or the error is permanent) do we fall back to
    `fallback_model` — the active provider's default — so the fallback stays within the
    user's chosen provider/client. Returns (response, note); note is non-empty on fallback,
    response is None if both fail.
    """
    kw = dict(messages=messages, temperature=temperature, max_tokens=max_tokens)
    if tools:
        kw["tools"] = tools
        kw["tool_choice"] = "auto"
    try:
        return await _create_with_retry(llm, model, kw), None
    except Exception as e:
        if fallback_model and model != fallback_model:
            try:
                r = await _create_with_retry(llm, fallback_model, kw)
                return r, (f"Model '{model}' is unavailable — fell back to "
                           f"{fallback_model}.")
            except Exception as e2:
                return None, str(e2)
        return None, str(e)


class _ToolCallObj:
    """Mimics an OpenAI tool_call object, reassembled from streaming deltas."""

    def __init__(self, id, name, arguments):
        self.id = id or ""
        self.type = "function"
        self.function = types.SimpleNamespace(name=name or "", arguments=arguments or "")

    def model_dump(self):
        return {"id": self.id, "type": "function",
                "function": {"name": self.function.name,
                             "arguments": self.function.arguments}}


async def _stream_chunks(llm, model, messages, tools, temperature, max_tokens):
    """Bridge the blocking streaming `create()` into an async chunk generator by
    pumping chunks from a worker thread through a thread-safe queue."""
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue = asyncio.Queue()
    DONE = object()

    def _worker():
        try:
            kw = dict(messages=messages, temperature=temperature,
                      max_tokens=max_tokens, stream=True)
            if tools:
                kw["tools"] = tools
                kw["tool_choice"] = "auto"
            for chunk in llm.chat.completions.create(model=model, **kw):
                loop.call_soon_threadsafe(queue.put_nowait, chunk)
        except Exception as e:
            loop.call_soon_threadsafe(queue.put_nowait, e)
        finally:
            loop.call_soon_threadsafe(queue.put_nowait, DONE)

    fut = loop.run_in_executor(None, _worker)
    try:
        while True:
            item = await queue.get()
            if item is DONE:
                break
            if isinstance(item, Exception):
                raise item
            yield item
    finally:
        await fut


async def _stream_llm(llm, model, messages, tools=None, temperature=0.1,
                      max_tokens=4096, content_scope="answer", fallback_model=None):
    """Stream one LLM call. Yields {"type":"delta","scope":...,"text":...} for content
    (scope=content_scope) and reasoning (scope="think"), then a terminal
    {"__done__": {content, tool_calls, note, error?}}. Falls back to `fallback_model`
    (the provider's default) on a model error and to a non-streamed call if streaming
    itself is unavailable."""
    attempts = [model] if not fallback_model or model == fallback_model else [model, fallback_model]
    for ai, m in enumerate(attempts):
        content, tool_acc, started = [], {}, False
        art_streams: dict = {}          # per tool-call-index artifact content readers
        streamed_artifacts: set = set()  # ids emitted live (so completion only closes them)
        try:
            async for chunk in _stream_chunks(llm, m, messages, tools, temperature,
                                              max_tokens):
                if not getattr(chunk, "choices", None):
                    continue
                started = True
                delta = chunk.choices[0].delta
                txt = getattr(delta, "content", None)
                if txt:
                    content.append(txt)
                    yield {"type": "delta", "scope": content_scope, "text": txt}
                rc = reasoning_of(delta)
                if rc:
                    yield {"type": "delta", "scope": "think", "text": rc}
                for tcd in (getattr(delta, "tool_calls", None) or []):
                    acc = tool_acc.setdefault(tcd.index,
                                              {"id": "", "name": "", "arguments": ""})
                    if getattr(tcd, "id", None):
                        acc["id"] = tcd.id
                    fn = getattr(tcd, "function", None)
                    if fn is not None:
                        if getattr(fn, "name", None):
                            acc["name"] = fn.name
                        if getattr(fn, "arguments", None):
                            acc["arguments"] += fn.arguments
                    # True artifact streaming: as the create/update args accumulate, emit
                    # the content live so the side panel fills in as the model writes it.
                    # Requires a known tool-call id so the streamed id matches the final one.
                    if acc["name"] in artifact_tools.TOOL_NAMES and acc["id"]:
                        art = art_streams.get(tcd.index)
                        if art is None:
                            art = artifact_stream.ArtifactArgStream(acc["name"], acc["id"])
                            art_streams[tcd.index] = art
                        open_meta, art_delta = art.feed(acc["arguments"])
                        if open_meta:
                            streamed_artifacts.add(open_meta["id"])
                            yield {"type": "artifact_open", "id": open_meta["id"],
                                   "title": open_meta["title"], "kind": open_meta["kind"],
                                   "language": open_meta["language"]}
                        if art_delta:
                            yield {"type": "artifact_delta", "id": art.artifact_id,
                                   "text": art_delta}
            tool_calls = [_ToolCallObj(a["id"] or f"call_{i}", a["name"], a["arguments"])
                          for i, a in sorted(tool_acc.items())]
            note = (f"Model '{model}' is unavailable — fell back to {fallback_model}."
                    if m != model else None)
            yield {"__done__": {"content": "".join(content), "tool_calls": tool_calls,
                                "note": note, "streamed_artifacts": streamed_artifacts}}
            return
        except Exception:
            if not started and ai == 0 and len(attempts) > 1:
                continue  # try the fallback model
            # Streaming unavailable → one non-streamed call (still yields a delta).
            resp, note = await _llm_create(llm, model, messages, tools=tools,
                                           temperature=temperature, max_tokens=max_tokens,
                                           fallback_model=fallback_model)
            if resp is None:
                yield {"__done__": {"content": "", "tool_calls": [],
                                    "note": f"LLM call failed: {note}", "error": True}}
                return
            msg = resp.choices[0].message
            full = msg.content or ""
            # If streaming already emitted a prefix before failing, emit ONLY the tail
            # so partial text is never duplicated (emit nothing if the retry diverged).
            emitted = "".join(content)
            if not emitted:
                new_text = full
            elif full.startswith(emitted):
                new_text = full[len(emitted):]
            else:
                new_text = ""
            if new_text:
                yield {"type": "delta", "scope": content_scope, "text": new_text}
            yield {"__done__": {"content": full or emitted,
                                "tool_calls": list(msg.tool_calls or []), "note": note}}
            return


# Friendly tool labels (Claude-style): name -> (running gerund, done past, icon).
TOOL_LABELS = {
    "search_schema": ("Looking up schema", "Looked up schema", "search"),
    "run_sql":       ("Querying BigQuery", "Queried BigQuery", "database"),
    "web_search":    ("Searching the web", "Searched the web", "globe"),
    "deep_research": ("Researching",       "Researched",       "telescope"),
    "web_fetch":     ("Fetching page",     "Fetched page",     "link"),
    "code_execution": ("Running code",     "Ran code",         "square-terminal"),
    "bash":          ("Running command",   "Ran command",      "terminal"),
    "text_editor":   ("Editing file",      "Edited file",      "file-pen"),
    "memory":        ("Updating memory",   "Updated memory",   "brain"),
    "create_artifact": ("Creating artifact", "Created artifact", "file-code"),
    "update_artifact": ("Updating artifact", "Updated artifact", "file-code"),
    "spawn_subagent": ("Delegating to subagent", "Subagent finished", "users"),
    "exit_plan_mode": ("Preparing plan", "Plan ready for review", "clipboard-list"),
}


def _tool_labels(name: str) -> tuple[str, str, str]:
    if name in TOOL_LABELS:
        return TOOL_LABELS[name]
    if name.startswith("mcp_"):
        short = name.split("_", 2)[-1]
        return (f"Using {short}", f"Used {short}", "plug")
    if name.startswith("rest_"):
        short = name[len("rest_"):]
        return (f"Calling {short}", f"Called {short}", "blocks")
    return (f"Using {name}", f"Used {name}", "wrench")


def _tool_input(name: str, args: dict) -> str:
    """Compact, human-readable summary of a tool's input for the card header/body."""
    if name == "run_sql":
        return (args.get("sql", "") or "").strip()[:600]
    if name == "search_schema":
        return (args.get("question", "") or "")[:300]
    if name == "web_search":
        return (args.get("query", "") or "")[:300]
    if name == "deep_research":
        return (args.get("topic", "") or "")[:300]
    if name == "web_fetch":
        return (args.get("url", "") or "")[:250]
    if name == "code_execution":
        return (args.get("code", "") or "")[:600]
    if name == "bash":
        return (args.get("command", "") or ("restart" if args.get("restart") else ""))[:300]
    if name == "text_editor":
        return f"{args.get('command', '')} {args.get('path', '')}".strip()[:300]
    if name == "memory":
        return (f"{args.get('command', '')} "
                f"{args.get('path') or args.get('old_path', '')}").strip()[:300]
    if name in ("create_artifact", "update_artifact"):
        return (args.get("title") or args.get("id") or "").strip()[:300]
    if name == "spawn_subagent":
        desc = (args.get("description") or "subtask").strip()
        prompt = (args.get("prompt") or "").strip().replace("\n", " ")
        return (f"{desc} — {prompt}" if prompt else desc)[:300]
    if name == "exit_plan_mode":
        return (args.get("plan") or "").strip()[:2000]
    return json.dumps(args, default=str)[:300]


async def _run_one_tool(name, args, tc_id, active_project, goal, top_k,
                        artifact_store=None, subagent=None) -> dict:
    """Execute ONE tool to completion and return a structured outcome (no UI events).
    Never raises — failures become {ok: False, ...} so the loop survives and the model
    can retry (Claude's is_error protocol, expressed in the tool-result string)."""
    try:
        if name == "spawn_subagent":
            if subagent is None:
                return {"id": tc_id, "name": name, "ok": False,
                        "result": "ERROR: subagents are not enabled for this turn."}
            out = await subagent(args.get("prompt", ""), args.get("description", "subtask"))
            out["id"], out["name"] = tc_id, name
            return out

        if name == "create_artifact":
            # Pin the artifact id to the tool-call id so a live-streamed artifact and its
            # final record share one id (and later update_artifact calls address it).
            a = artifact_tools.create(args, artifact_store if artifact_store is not None else {},
                                      artifact_id=tc_id)
            return {"id": tc_id, "name": name, "ok": True, "artifact": a,
                    "result": f"Created artifact '{a['title']}' (id {a['id']}). It is shown "
                              "in the side panel; describe it briefly in your reply.",
                    "summary": f"{a['title']} · {a['kind']}"}

        if name == "update_artifact":
            a, err = artifact_tools.update(args, artifact_store if artifact_store is not None else {})
            if err:
                return {"id": tc_id, "name": name, "ok": False, "error": err,
                        "result": f"ERROR: {err}"}
            return {"id": tc_id, "name": name, "ok": True, "artifact": a,
                    "result": f"Updated artifact '{a['title']}' (id {a['id']}, v{a['version']}).",
                    "summary": f"{a['title']} · v{a['version']}"}

        if name == "search_schema":
            q = args.get("question", goal)
            result = await asyncio.to_thread(schema_catalog.search_schema, q, active_project, top_k)
            return {"id": tc_id, "name": name, "ok": True, "result": result,
                    "summary": f"{result.count('TABLE:')} tables · {len(result):,} chars"}

        if name == "run_sql":
            sql = args.get("sql", "")
            res = await asyncio.to_thread(bigquery.execute_sql, sql, active_project)
            result = res["agent_text"]
            if not res.get("ok"):
                return {"id": tc_id, "name": name, "ok": False,
                        "result": f"ERROR: run_sql failed. {result[:500]} "
                                  f"Fix the SQL and retry.",
                        "error": result[:400]}
            out = {"id": tc_id, "name": name, "ok": True, "result": result,
                   "summary": result[:300]}
            if res.get("rows"):
                out["table"] = {"columns": res["columns"],
                                "rows": res["rows"][:config.MAX_TABLE_ROWS_UI],
                                "total": res["total_rows"], "bytes": res["bytes"]}
                out["summary"] = (f"{res['total_rows']} rows · "
                                  f"{util.fmt_bytes(res['bytes'])} scanned")
            return out

        if name == "web_search":
            from . import integrations
            q = args.get("query", goal)
            result, sources = await asyncio.to_thread(
                integrations.web_search_with_sources, q)
            return {"id": tc_id, "name": name, "ok": True, "result": result,
                    "summary": result[:300], "sources": sources}

        if name == "deep_research":
            from . import integrations
            topic = args.get("topic", goal)
            result, sources = await asyncio.to_thread(
                integrations.research_with_sources, topic)
            return {"id": tc_id, "name": name, "ok": True, "result": result,
                    "summary": (result.split(chr(10))[1] if chr(10) in result
                                else result[:160]),
                    "sources": sources}

        if name == "web_fetch":
            from . import integrations
            result, sources = await asyncio.to_thread(
                integrations.web_fetch, args.get("url", ""))
            ok = not result.startswith("web_fetch_tool_error")
            out = {"id": tc_id, "name": name, "ok": ok, "result": result,
                   "summary": result.split("\n\n")[0][:300]}
            if sources:
                out["sources"] = sources
            if not ok:
                out["error"] = result
            return out

        if name == "code_execution":
            from . import integrations
            result = await asyncio.to_thread(integrations.run_python,
                                             args.get("code", ""))
            ok = result.startswith("return_code: 0")
            out = {"id": tc_id, "name": name, "ok": ok, "result": result,
                   "summary": result[:400]}
            if not ok:
                out["error"] = result
            return out

        if name == "bash":
            from . import integrations
            result = await asyncio.to_thread(integrations.run_bash,
                                             args.get("command", ""),
                                             bool(args.get("restart")))
            ok = not result.startswith(("Rejected:", "Error:", "Timed out"))
            out = {"id": tc_id, "name": name, "ok": ok, "result": result,
                   "summary": result[:300]}
            if not ok:
                out["error"] = result
            return out

        if name in ("text_editor", "memory"):
            from . import integrations
            sub = active_project or "general"
            if name == "text_editor":
                root = integrations.SANDBOX_ROOT / sub
                result = await asyncio.to_thread(integrations.text_editor, args, root)
            else:
                root = integrations.MEMORY_ROOT / sub
                result = await asyncio.to_thread(integrations.memory_tool, args, root)
            ok = not (result.startswith("Error") or "does not exist" in result)
            out = {"id": tc_id, "name": name, "ok": ok, "result": result,
                   "summary": result[:300]}
            if not ok:
                out["error"] = result
            return out

        from . import integrations  # plugin / connector / MCP tool
        result = await asyncio.to_thread(integrations.run_tool, name, args)
        return {"id": tc_id, "name": name, "ok": True, "result": result,
                "summary": result[:300]}

    except Exception as e:
        cause = str(e)[:300]
        return {"id": tc_id, "name": name, "ok": False, "error": cause,
                "result": (f"ERROR: {name} failed: {cause}. "
                           "Fix the input and retry, or proceed without it.")}


def _completion_events(out: dict, streamed_artifacts: set | None = None):
    """Derive the UI completion event(s) for a finished tool outcome (id-keyed). Artifacts
    whose content was already streamed live get only a final ``artifact_close`` (no repeat
    open + full-content delta)."""
    streamed_artifacts = streamed_artifacts or set()
    if not out.get("ok"):
        return [{"type": "tool_error", "id": out["id"], "name": out["name"],
                 "text": out.get("error") or out.get("result", "Tool failed.")}]
    evs = [{"type": "tool_result", "id": out["id"], "name": out["name"],
            "summary": out.get("summary", "")}]
    if "table" in out:
        t = out["table"]
        evs.append({"type": "table", "id": out["id"], "columns": t["columns"],
                    "rows": t["rows"], "total": t["total"], "bytes": t["bytes"]})
    if out.get("sources"):
        evs.append({"type": "sources", "id": out["id"], "items": out["sources"]})
    if out.get("artifact"):
        a = out["artifact"]
        if a["id"] not in streamed_artifacts:
            # Not streamed live → emit the whole artifact now (open + full content).
            evs.append({"type": "artifact_open", "id": a["id"], "title": a["title"],
                        "kind": a["kind"], "language": a.get("language", "")})
            evs.append({"type": "artifact_delta", "id": a["id"], "text": a["content"]})
        evs.append({"type": "artifact_close", "id": a["id"], "version": a["version"]})
    return evs


async def run_turn(goal: str, history: list[dict], active_project: str | None,
                   model: str, project_instructions: str = "",
                   top_k: int = 6, max_steps: int = 8,
                   web_search: bool = False, skill_instructions: str = "",
                   research: bool = False, extra_tools: list | None = None,
                   effort: str = "High", parallel: bool = True,
                   web_fetch: bool = False, code_exec: bool = False, bash: bool = False,
                   text_editor: bool = False, memory: bool = False,
                   provider: str | None = None, turn_id: str | None = None,
                   permission_mode: str | None = None, artifacts: bool = False,
                   user_profile: str = "", subagents: bool = False):
    """Drive one agent turn, yielding events. `history` is prior (role/content) turns.

    `turn_id` + `permission_mode` enable the interactive HITL gate: when set (and the
    mode is not "auto"), a sensitive tool call yields `approval_required` and the turn
    suspends until the reply endpoint resolves it (declined on timeout). With no
    turn_id or in "auto" mode, tools run without prompting (prior behavior).

    `provider` (optional) selects the model provider; otherwise it is inferred from a
    ``provider/model`` prefix on `model` or the configured default. BYOK: a missing
    key surfaces as a clean error event rather than crashing the stream.
    """
    cfg = EFFORT.get(effort, EFFORT["High"])
    temperature = cfg["temp"]
    steps = max(cfg["steps"], 14 if research else 0)
    # HITL gate is active only with a turn_id (a reply channel) and a non-auto mode.
    perm_mode = (permission_mode or config.PERMISSION_MODE)
    gate_on = bool(turn_id) and perm_mode != "auto"
    # Plan mode: research read-only, present a plan, and only mutate after approval. It
    # needs an interactive reply channel (turn_id); without one it degrades to no-op.
    plan_mode = bool(turn_id) and perm_mode == "plan"

    bq_on = bigquery_tools.enabled()
    extra_sections = []
    if plan_mode:
        extra_sections.append(PLAN_MODE_SECTION)
    if bq_on:
        extra_sections.append(bigquery_tools.system_prompt_section())
    if artifacts:
        extra_sections.append(artifact_tools.system_prompt_section())
    # Long-horizon context management: compact older turns so a long conversation
    # never overflows the model's context window (catalog handles a provider/ prefix).
    history, _ = context.compact_for_model(list(history or []), model)
    messages = [{"role": "system",
                 "content": prompts.build_system_prompt(
                     extra_sections=extra_sections or None, memory=memory,
                     user_profile=user_profile,
                     project_instructions=project_instructions,
                     skill_instructions=skill_instructions, research=research)},
                *history, {"role": "user", "content": goal}]
    tools = list(bigquery_tools.TOOL_SPECS) if bq_on else []
    if artifacts:
        tools.extend(artifact_tools.TOOL_SPECS)
    artifact_store: dict = {}
    if web_search or research:
        tools.append(WEB_SEARCH_TOOL)
    if research:
        tools.append(RESEARCH_TOOL)
    if web_fetch:
        tools.append(WEB_FETCH_TOOL)
    if code_exec:
        tools.append(CODE_EXECUTION_TOOL)
    if bash:
        tools.append(BASH_TOOL)
    if text_editor:
        tools.append(TEXT_EDITOR_TOOL)
    if memory:
        tools.append(MEMORY_TOOL)
    if subagents:
        tools.append(TASK_TOOL)
    if plan_mode:
        tools.append(PLAN_TOOL)
    if extra_tools:
        tools.extend(extra_tools)
    # H6: enforce tool enablement at DISPATCH, not just by which schemas we send.
    # Only names present in this turn's assembled tool set may execute, so a
    # hallucinated or injected tool call cannot reach the dispatcher.
    allowed_tool_names = {t["function"]["name"] for t in tools}
    try:
        llm, model, fallback_model = resolve_turn_client(model, provider)
    except LLMConfigError as e:
        yield {"type": "error", "text": str(e)}
        return

    if bq_on:
        try:
            await asyncio.to_thread(schema_catalog.ensure_catalog)
        except Exception:
            pass

    # ---- Planning pass (High/Max): explicit thinking before acting, streamed ----
    if cfg["plan"]:
        plan_msgs = messages + [{"role": "user", "content":
            "Think first. In 2–5 short sentences outline how you'll approach this — what "
            "to look up, compute, and verify. Do NOT call tools or answer yet; plan only."}]
        t0 = time.monotonic()
        yield {"type": "think_open", "phase": "plan"}
        done = {}
        async for ev in _stream_llm(llm, model, plan_msgs, None, temperature, 400,
                                    content_scope="think", fallback_model=fallback_model):
            if "__done__" in ev:
                done = ev["__done__"]
            else:
                yield ev
        yield {"type": "think_close", "elapsed": max(1, round(time.monotonic() - t0))}
        plan = (done.get("content") or "").strip()
        if plan:
            messages.append({"role": "assistant", "content": f"My plan: {plan}"})

    # A delegated subtask runs a fresh, isolated agent turn: same model/provider/effort
    # and tool CAPABILITIES, but auto-permission (no HITL to answer), no UI artifacts, and
    # no further nesting (subagents=False). Only its final answer flows back to the parent.
    async def _run_subagent(sub_prompt: str, description: str) -> dict:
        answer_buf: list[str] = []
        tools_used: list[str] = []
        err: str | None = None
        async for ev in run_turn(
                sub_prompt, [], active_project, model, project_instructions="",
                top_k=top_k, web_search=web_search, research=research, web_fetch=web_fetch,
                code_exec=code_exec, bash=bash, text_editor=text_editor, memory=memory,
                artifacts=False, effort=effort, parallel=parallel, provider=provider,
                permission_mode="auto", subagents=False):
            t = ev.get("type")
            if t in ("answer_open", "answer_to_think"):
                answer_buf.clear()          # keep only the final answer block
            elif t == "delta" and ev.get("scope") == "answer":
                answer_buf.append(ev.get("text", ""))
            elif t == "tool":
                tools_used.append(ev.get("name", ""))
            elif t == "error":
                err = ev.get("text", "subagent error")
        if err:
            return {"ok": False, "error": err,
                    "result": f"The subagent failed: {err}. Proceed without it, or retry "
                              "with a clearer, more self-contained prompt."}
        answer = "".join(answer_buf).strip() or "(the subagent produced no answer)"
        used = ", ".join(dict.fromkeys(x for x in tools_used if x)) or "no tools"
        return {"ok": True, "result": answer,
                "summary": f"{(description or 'subtask')[:60]} · used {used} · "
                           f"{len(answer):,} chars"}

    subagent_runner = _run_subagent if subagents else None

    # ---- Main tool-calling loop (streamed) ----
    final_text = None
    answer_shown = False
    out_parts: list[str] = []  # accumulated generated text, for the usage estimate
    for _ in range(steps):
        yield {"type": "answer_open"}
        done = {}
        async for ev in _stream_llm(llm, model, messages, tools, temperature, 4096,
                                    content_scope="answer", fallback_model=fallback_model):
            if "__done__" in ev:
                done = ev["__done__"]
            else:
                yield ev
        if done.get("error"):
            yield {"type": "answer_to_think", "phase": "narration", "elapsed": 0}
            yield {"type": "error", "text": done.get("note", "LLM call failed.")}
            return

        content = done.get("content") or ""
        if content:
            out_parts.append(content)
        tool_calls = done.get("tool_calls") or []
        assistant_msg = {"role": "assistant", "content": content}
        if tool_calls:
            assistant_msg["tool_calls"] = [tc.model_dump() for tc in tool_calls]
        messages.append(assistant_msg)

        if not tool_calls:
            if not content.strip():
                # blank answer → drop the empty bubble and nudge the model
                yield {"type": "answer_to_think", "phase": "narration", "elapsed": 0}
                messages.append({"role": "user",
                                 "content": "Respond with your answer or call a tool."})
                continue
            final_text = content
            if cfg["verify"]:
                # the streamed answer is a DRAFT; the verify pass writes the final one
                yield {"type": "answer_to_think", "phase": "plan", "elapsed": 1}
            else:
                answer_shown = True
            break

        # Tool calls → any streamed content was narration; fold it into a thinking block.
        yield {"type": "answer_to_think", "phase": "narration", "elapsed": 1}

        # Show a "running" card for every tool call up-front (parallel calls all
        # appear at once), then execute — concurrently when independent.
        calls = []
        blocked_outcomes = []
        for tc in tool_calls:
            try:
                args = json.loads(tc.function.arguments or "{}")
            except Exception:
                args = {}
            name = tc.function.name
            # H6: refuse any tool not enabled for this turn (hallucinated/injected
            # names). Still emit a card + a tool result so the loop stays consistent.
            if name not in allowed_tool_names:
                run_lbl, done_lbl, icon = _tool_labels(name)
                yield {"type": "tool", "id": tc.id, "name": name,
                       "input": _tool_input(name, args), "label_running": run_lbl,
                       "label_done": done_lbl, "icon": icon}
                yield {"type": "tool_error", "id": tc.id, "name": name,
                       "text": f"Tool '{name}' is not enabled for this turn."}
                blocked_outcomes.append({"id": tc.id, "name": name, "ok": False,
                    "result": (f"ERROR: tool '{name}' is not enabled and was not run. "
                               "Use only the tools provided.")})
                continue
            run_lbl, done_lbl, icon = _tool_labels(name)
            yield {"type": "tool", "id": tc.id, "name": name,
                   "input": _tool_input(name, args), "label_running": run_lbl,
                   "label_done": done_lbl, "icon": icon}
            # Plan mode: `exit_plan_mode` presents the plan for approval; approving LEAVES
            # plan mode (the rest of this turn runs under the normal HITL gate). Every other
            # state-changing tool is blocked until then.
            if plan_mode and name == "exit_plan_mode":
                yield {"type": "approval_required", "turn_id": turn_id, "id": tc.id,
                       "name": name, "input": _tool_input(name, args)}
                approved = await permissions.registry.wait(
                    turn_id, tc.id, config.PERMISSION_TIMEOUT_SEC)
                if approved:
                    plan_mode = False
                    perm_mode, gate_on = "ask", True   # mutations now prompt, not blocked
                    yield {"type": "tool_result", "id": tc.id, "name": name,
                           "summary": "Plan approved — implementing"}
                    blocked_outcomes.append({"id": tc.id, "name": name, "ok": True,
                        "result": ("The user APPROVED the plan. Plan mode is now OFF — carry "
                                   "it out. Sensitive actions will still ask for confirmation.")})
                else:
                    yield {"type": "tool_result", "id": tc.id, "name": name,
                           "summary": "Kept planning"}
                    blocked_outcomes.append({"id": tc.id, "name": name, "ok": True,
                        "result": ("The user did NOT approve the plan and wants to keep "
                                   "planning. Do not make any changes; refine the plan "
                                   "(ask what to adjust if unclear) and call exit_plan_mode "
                                   "again.")})
                continue
            if plan_mode and permissions.is_sensitive(name):
                yield {"type": "tool_error", "id": tc.id, "name": name,
                       "text": "Blocked in plan mode — research only, then present a plan."}
                blocked_outcomes.append({"id": tc.id, "name": name, "ok": False,
                    "result": (f"BLOCKED: '{name}' cannot run in PLAN MODE. Do not modify "
                               "anything yet. Finish researching read-only, then call "
                               "exit_plan_mode with your plan for the user to approve.")})
                continue
            # HITL: suspend for a user decision before running a sensitive tool.
            if gate_on and permissions.requires_approval(name, perm_mode):
                yield {"type": "approval_required", "turn_id": turn_id, "id": tc.id,
                       "name": name, "input": _tool_input(name, args)}
                approved = await permissions.registry.wait(
                    turn_id, tc.id, config.PERMISSION_TIMEOUT_SEC)
                if not approved:
                    yield {"type": "tool_error", "id": tc.id, "name": name,
                           "text": "Declined by the user."}
                    blocked_outcomes.append({"id": tc.id, "name": name, "ok": False,
                        "result": (f"The user DECLINED to run '{name}'. Do not retry it; "
                                   "continue without it or ask how to proceed.")})
                    continue
            calls.append((tc.id, name, args))

        streamed = done.get("streamed_artifacts") or set()
        if parallel and len(calls) > 1:
            tasks = [asyncio.create_task(
                _run_one_tool(n, a, i, active_project, goal, top_k, artifact_store,
                              subagent=subagent_runner))
                for (i, n, a) in calls]
            outcomes = []
            for fut in asyncio.as_completed(tasks):
                out = await fut
                outcomes.append(out)
                for ev in _completion_events(out, streamed):
                    yield ev
        else:
            outcomes = []
            for (i, n, a) in calls:
                out = await _run_one_tool(n, a, i, active_project, goal, top_k, artifact_store,
                                          subagent=subagent_runner)
                outcomes.append(out)
                for ev in _completion_events(out, streamed):
                    yield ev

        # Feed every tool result back to the model, one message per tool_call_id
        # (executed + any blocked-by-enablement calls, preserving the model's order).
        by_id = {o["id"]: o for o in (outcomes + blocked_outcomes)}
        for tc in tool_calls:
            if tc.id in by_id:
                # Cap any single oversized tool output so it can't overflow the window.
                messages.append({"role": "tool", "tool_call_id": tc.id,
                                 "content": context.truncate_tool_result(by_id[tc.id]["result"])})

    if final_text is None:
        final_text = ("Stopped after the step limit without a final answer. "
                      "Try narrowing the question or lowering effort.")
        yield {"type": "answer_open"}
        yield {"type": "delta", "scope": "answer", "text": final_text}
        answer_shown = True

    # ---- Verification pass (Max): self-critique and refine, streamed ----
    if cfg["verify"] and not answer_shown and not final_text.startswith("Stopped"):
        t0 = time.monotonic()
        yield {"type": "think_open", "phase": "verify"}
        yield {"type": "delta", "scope": "think",
               "text": "Verifying the answer: checking the numbers, sources, and "
                       "completeness…"}
        messages.append({"role": "assistant", "content": final_text})
        v_msgs = messages + [{"role": "user", "content":
            "Critically review the answer you just gave for correctness, completeness, and "
            "unsupported claims, then produce the best final answer. If it was already "
            "correct, keep it; otherwise fix it. Output ONLY the final answer itself, in "
            "Markdown. Do NOT add any header, title, label, or preamble such as "
            "'Corrected Answer', 'Final Answer', 'Verified', or 'Here is' — begin directly "
            "with the answer content."}]
        yield {"type": "answer_open"}
        done = {}
        async for ev in _stream_llm(llm, model, v_msgs, None, temperature, 4096,
                                    content_scope="answer", fallback_model=fallback_model):
            if "__done__" in ev:
                done = ev["__done__"]
            else:
                yield ev
        yield {"type": "think_close", "elapsed": max(1, round(time.monotonic() - t0))}
        vtext = _strip_answer_label((done.get("content") or "").strip())
        if vtext:
            final_text = vtext
            out_parts.append(vtext)
        else:  # verify produced nothing — show the draft as the answer
            yield {"type": "delta", "scope": "answer", "text": final_text}
        answer_shown = True

    # ---- Usage / cost meter (one event at the end of a successful turn) ----
    yield usage.build_usage(model, messages, "".join(out_parts))
