"""
AJ360 BigQuery agent — UI-agnostic orchestration layer.

`run_turn` is an async generator that drives the GLM tool-calling loop and
*yields structured events* describing what is happening. Any presentation layer
(Reflex, Chainlit, CLI) can consume the stream and render it however it likes —
the agent knows nothing about the UI.

Event shapes (all dicts with a "type"):
  {"type": "thought",     "text": str, "phase": str,         # reasoning; phase is
                          "elapsed": int}                    #   "plan"|"narration"
  {"type": "verify",      "text": str}                       # self-verification pass
  {"type": "tool",        "name": str, "detail": str}        # a tool call started
  {"type": "tool_result", "name": str, "summary": str}       # non-table tool output
  {"type": "sources",     "items": list}                     # web/research citations:
                          #   [{"title": str, "url": str, "snippet": str}, ...]
  {"type": "table",       "columns": list, "rows": list,     # SELECT result
                          "total": int, "bytes": int}
  {"type": "final",       "text": str, "verify_elapsed": int}  # the answer
  {"type": "error",       "text": str}

Effort levels (Low/Medium/High/Max) control the depth of multi-turn thinking:
  Low/Medium — direct tool loop, no extra reasoning passes.
  High       — a planning pass before acting.
  Max        — planning pass + a self-verification pass before the final answer.
"""
from __future__ import annotations

import json
import time
import types
import asyncio

from . import core

TOOLS = [
    {"type": "function", "function": {
        "name": "search_schema",
        "description": "Retrieve exact table names, columns, types, candidate join keys, "
                       "AND any relevant wiki / project-KB findings. ALWAYS call before "
                       "writing SQL.",
        "parameters": {"type": "object", "properties": {
            "question": {"type": "string", "description": "What you need schema for."}},
            "required": ["question"]}}},
    {"type": "function", "function": {
        "name": "run_sql",
        "description": "Validate (dry-run) and run a complete BigQuery standard-SQL SELECT. "
                       "Read-only: non-SELECT statements are rejected.",
        "parameters": {"type": "object", "properties": {
            "sql": {"type": "string", "description": "Full BigQuery standard-SQL query."}},
            "required": ["sql"]}}},
]

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

# Effort -> behaviour. `steps` is the tool-loop iteration cap; `plan`/`verify` add
# explicit thinking passes; `temp` raises exploration at higher effort.
EFFORT = {
    "Low":    {"steps": 3,  "plan": False, "verify": False, "temp": 0.0},
    "Medium": {"steps": 7,  "plan": False, "verify": False, "temp": 0.1},
    "High":   {"steps": 11, "plan": True,  "verify": False, "temp": 0.2},
    "Max":    {"steps": 16, "plan": True,  "verify": True,  "temp": 0.3},
}

SYSTEM_PROMPT = f"""You are a BigQuery analytics agent for the AJ360 (Al Jazeera 360) OTT platform.
Project: `{core.PROJECT_ID}`  Region: EU. Dialect: BigQuery standard SQL.

You write and run SQL yourself. Operating loop:
1. Call `search_schema` to get EXACT table and column names AND check the knowledge wiki.
2. Write fully-qualified SQL using the EXACT table names from search_schema.
3. Call `run_sql`. If it returns an error, fix the SQL and retry.
4. When you have data, write the final answer with exact numbers in a Markdown table.

This chat is READ-ONLY: only SELECT runs. Do not attempt INSERT/UPDATE/DELETE/DDL.

Hard rules (AJ360-specific):
- Profile suspicious columns before trusting them.
- DATE vs TIMESTAMP: confirm from schema before comparing.
- Banned aliases: {', '.join(sorted(core.BANNED_ALIASES))}.
- Device: always `devicetype`, NEVER `device_category`.
- video_completion_rate is broken -> SAFE_DIVIDE workaround.
- Aggregate on series_id, NOT series_title.
- Default window: CURRENT_DATE() - 2.
- GA4 tables are huge: filter by stream_id + short window for UNNEST.
- Search funnels are separate per platform.

How to work (shown to the user as your reasoning):
- Before calling tools, say in ONE short sentence what you're about to do and why.
- After seeing tool results, note in ONE short sentence what you learned before the
  next step. Keep this running narration concise — it is your visible thinking.
- When you need several INDEPENDENT pieces of information, request those tools TOGETHER
  in one step so they run in parallel. Only sequence tools when one genuinely depends
  on another's output (e.g. search_schema before run_sql).
- If a tool returns an error, read it, correct your input, and retry — or explain why
  you can't proceed. Never give up silently.

Be terse, evidence-first, American English. Exact numbers.
"""


def _system_prompt(project_instructions: str = "", skill_instructions: str = "",
                   research: bool = False, memory: bool = False) -> str:
    sp = SYSTEM_PROMPT
    if memory:
        sp += ("\n\n# MEMORY PROTOCOL\n"
               "You have a persistent `memory` tool backed by /memories. At the START of a "
               "task, ALWAYS call `memory` with command=view, path=/memories to recover "
               "relevant prior context. Record durable facts, decisions, and task state "
               "with memory create / str_replace so they survive across conversations.\n")
    if project_instructions.strip():
        sp += ("\n\n# PROJECT-SPECIFIC INSTRUCTIONS\n"
               "You are operating inside a project. Adhere strictly to:\n"
               f"{project_instructions.strip()}\n")
    if skill_instructions.strip():
        sp += ("\n\n# ACTIVE SKILL\n"
               "Follow this skill's guidance for this turn:\n"
               f"{skill_instructions.strip()}\n")
    if research:
        sp += ("\n\n# RESEARCH MODE\n"
               "Use `deep_research` ONCE to gather parallel multi-source findings, then "
               "cross-check the sources and synthesize a structured answer that CITES the "
               "sources you used.\n")
    return sp


import re as _re

_LABEL_RE = _re.compile(
    r"^\s*(?:#{1,6}\s*)?(?:\*\*)?\s*"
    r"(?:corrected|final|verified|revised|improved)\s+answer\s*(?:\*\*)?\s*:?\s*\n+",
    _re.IGNORECASE)


def _strip_answer_label(text: str) -> str:
    """Drop a leading 'Corrected Answer'/'Final Answer' heading the verify pass may
    still emit, so the refined answer reads as a seamless replacement."""
    return _LABEL_RE.sub("", text, count=1).lstrip()


async def _llm_create(llm, model, messages, tools=None, temperature=0.1, max_tokens=4096):
    """LLM create with a single fallback to AGENT_MODEL if `model` errors.

    Returns (response, note). note is a non-empty string when a fallback happened
    or (response None) when both calls failed.
    """
    kw = dict(messages=messages, temperature=temperature, max_tokens=max_tokens)
    if tools:
        kw["tools"] = tools
        kw["tool_choice"] = "auto"
    try:
        return await asyncio.to_thread(llm.chat.completions.create, model=model, **kw), None
    except Exception as e:
        if model != core.AGENT_MODEL:
            try:
                r = await asyncio.to_thread(
                    llm.chat.completions.create, model=core.AGENT_MODEL, **kw)
                return r, (f"Model '{model}' is unavailable — fell back to "
                           f"{core.AGENT_MODEL}.")
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
                      max_tokens=4096, content_scope="answer"):
    """Stream one LLM call. Yields {"type":"delta","scope":...,"text":...} for content
    (scope=content_scope) and reasoning (scope="think"), then a terminal
    {"__done__": {content, tool_calls, note, error?}}. Falls back to AGENT_MODEL on a
    model error and to a non-streamed call if streaming itself is unavailable."""
    attempts = [model] if model == core.AGENT_MODEL else [model, core.AGENT_MODEL]
    for ai, m in enumerate(attempts):
        content, tool_acc, started = [], {}, False
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
                rc = getattr(delta, "reasoning_content", None)
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
            tool_calls = [_ToolCallObj(a["id"] or f"call_{i}", a["name"], a["arguments"])
                          for i, a in sorted(tool_acc.items())]
            note = (f"Model '{model}' is unavailable — fell back to {core.AGENT_MODEL}."
                    if m != model else None)
            yield {"__done__": {"content": "".join(content), "tool_calls": tool_calls,
                                "note": note}}
            return
        except Exception:
            if not started and ai == 0 and len(attempts) > 1:
                continue  # try the fallback model
            # Streaming unavailable → one non-streamed call (still yields a delta).
            resp, note = await _llm_create(llm, model, messages, tools=tools,
                                           temperature=temperature, max_tokens=max_tokens)
            if resp is None:
                yield {"__done__": {"content": "", "tool_calls": [],
                                    "note": f"LLM call failed: {note}", "error": True}}
                return
            msg = resp.choices[0].message
            if msg.content:
                yield {"type": "delta", "scope": content_scope, "text": msg.content}
            yield {"__done__": {"content": msg.content or "",
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
    return json.dumps(args, default=str)[:300]


async def _run_one_tool(name, args, tc_id, active_project, goal, top_k) -> dict:
    """Execute ONE tool to completion and return a structured outcome (no UI events).
    Never raises — failures become {ok: False, ...} so the loop survives and the model
    can retry (Claude's is_error protocol, expressed in the tool-result string)."""
    try:
        if name == "search_schema":
            q = args.get("question", goal)
            result = await asyncio.to_thread(core.search_schema, q, active_project, top_k)
            return {"id": tc_id, "name": name, "ok": True, "result": result,
                    "summary": f"{result.count('TABLE:')} tables · {len(result):,} chars"}

        if name == "run_sql":
            sql = args.get("sql", "")
            res = await asyncio.to_thread(core.execute_sql, sql, active_project)
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
                                "rows": res["rows"][:core.MAX_TABLE_ROWS_UI],
                                "total": res["total_rows"], "bytes": res["bytes"]}
                out["summary"] = (f"{res['total_rows']} rows · "
                                  f"{core.fmt_bytes(res['bytes'])} scanned")
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


def _completion_events(out: dict):
    """Derive the UI completion event(s) for a finished tool outcome (id-keyed)."""
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
    return evs


async def run_turn(goal: str, history: list[dict], active_project: str | None,
                   model: str, project_instructions: str = "",
                   top_k: int = 6, max_steps: int = 8,
                   web_search: bool = False, skill_instructions: str = "",
                   research: bool = False, extra_tools: list | None = None,
                   effort: str = "High", parallel: bool = True,
                   web_fetch: bool = False, code_exec: bool = False, bash: bool = False,
                   text_editor: bool = False, memory: bool = False):
    """Drive one agent turn, yielding events. `history` is prior (role/content) turns."""
    cfg = EFFORT.get(effort, EFFORT["High"])
    temperature = cfg["temp"]
    steps = max(cfg["steps"], 14 if research else 0)

    messages = [{"role": "system",
                 "content": _system_prompt(project_instructions, skill_instructions,
                                           research, memory=memory)},
                *history, {"role": "user", "content": goal}]
    tools = list(TOOLS)
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
    if extra_tools:
        tools.extend(extra_tools)
    llm = core.get_llm_client()

    try:
        await asyncio.to_thread(core.ensure_catalog)
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
                                    content_scope="think"):
            if "__done__" in ev:
                done = ev["__done__"]
            else:
                yield ev
        yield {"type": "think_close", "elapsed": max(1, round(time.monotonic() - t0))}
        plan = (done.get("content") or "").strip()
        if plan:
            messages.append({"role": "assistant", "content": f"My plan: {plan}"})

    # ---- Main tool-calling loop (streamed) ----
    final_text = None
    answer_shown = False
    for _ in range(steps):
        yield {"type": "answer_open"}
        done = {}
        async for ev in _stream_llm(llm, model, messages, tools, temperature, 4096,
                                    content_scope="answer"):
            if "__done__" in ev:
                done = ev["__done__"]
            else:
                yield ev
        if done.get("error"):
            yield {"type": "answer_to_think", "phase": "narration", "elapsed": 0}
            yield {"type": "error", "text": done.get("note", "LLM call failed.")}
            return

        content = done.get("content") or ""
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
        for tc in tool_calls:
            try:
                args = json.loads(tc.function.arguments or "{}")
            except Exception:
                args = {}
            name = tc.function.name
            run_lbl, done_lbl, icon = _tool_labels(name)
            yield {"type": "tool", "id": tc.id, "name": name,
                   "input": _tool_input(name, args), "label_running": run_lbl,
                   "label_done": done_lbl, "icon": icon}
            calls.append((tc.id, name, args))

        if parallel and len(calls) > 1:
            tasks = [asyncio.create_task(
                _run_one_tool(n, a, i, active_project, goal, top_k))
                for (i, n, a) in calls]
            outcomes = []
            for fut in asyncio.as_completed(tasks):
                out = await fut
                outcomes.append(out)
                for ev in _completion_events(out):
                    yield ev
        else:
            outcomes = []
            for (i, n, a) in calls:
                out = await _run_one_tool(n, a, i, active_project, goal, top_k)
                outcomes.append(out)
                for ev in _completion_events(out):
                    yield ev

        # Feed every tool result back to the model, one message per tool_call_id.
        by_id = {o["id"]: o for o in outcomes}
        for (i, n, a) in calls:
            messages.append({"role": "tool", "tool_call_id": i,
                             "content": by_id[i]["result"]})

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
                                    content_scope="answer"):
            if "__done__" in ev:
                done = ev["__done__"]
            else:
                yield ev
        yield {"type": "think_close", "elapsed": max(1, round(time.monotonic() - t0))}
        vtext = _strip_answer_label((done.get("content") or "").strip())
        if vtext:
            final_text = vtext
        else:  # verify produced nothing — show the draft as the answer
            yield {"type": "delta", "scope": "answer", "text": final_text}
        answer_shown = True
