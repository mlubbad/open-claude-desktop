"""
Open Claude Desktop agent — UI-agnostic orchestration layer.

`run_turn` is an async generator that drives the model's tool-calling loop and
*yields structured events* describing what is happening. Any presentation layer
(desktop client, CLI) can consume the stream and render it however it likes —
the agent knows nothing about the UI.

Event shapes (all dicts with a "type"). These are what `run_turn` actually
yields; the API layer prepends {"type": "turn_start", "turn_id": str} and appends
a terminal {"type": "done"} after the stream ends.

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
  {"type": "tool_output_delta", "id": str, "stream": str,           # live stdout/stderr
                          "text": str}                              #   from code_execution
  {"type": "files",       "id": str, "items": list}                # files a run produced
                          # items: [{"path": str, "size": int, "kind": str}]
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

  Connector sign-in (the `authenticate` tool, interactive turns — opens a browser):
  {"type": "auth_url", "id": str, "provider": str, "url": str}  # consent URL to open

  Structured clarifying question (interactive turns only; the turn ENDS after this —
  the user's answer arrives as the next user turn):
  {"type": "question", "id": str,
   "questions": [{"title": str, "options": [str], "allow_other": bool}]}

  Failure:
  {"type": "error", "text": str}                             # the turn could not proceed

Effort levels (Low/Medium/High/Extra/Max) control the depth of multi-turn thinking:
  Low/Medium — direct tool loop, no extra reasoning passes.
  High       — a planning pass before acting.
  Max        — planning pass + a self-verification pass before the final answer.
Each level also sets the tool-round budget (see EFFORT). Exhausting it never ends the
turn with a harness error: the model is warned as the budget runs low and, if it still
runs out, is forced through one final no-tools call to synthesize its best answer from
everything gathered.
"""
from __future__ import annotations

import asyncio
import json
import random
import re
import time
import types

from . import (
    artifact_stream,
    artifact_tools,
    auth_flows,
    bigquery,
    bigquery_tools,
    config,
    context,
    egress_policy,
    events,
    observability,
    permissions,
    prompts,
    schema_catalog,
    settings,
    usage,
    util,
    vision,
)
from .llm import LLMConfigError, reasoning_of, resolve_turn_client
from .llm import catalog as llm_catalog

WEB_SEARCH_TOOL = {"type": "function", "function": {
    "name": "web_search",
    "description": "Search the public web for current information beyond your training data "
                   "or the connected data sources (definitions, recent events, benchmarks).",
    "parameters": {"type": "object", "properties": {
        "query": {"type": "string", "description": "The search query."}},
        "required": ["query"]}}}

PROJECT_KB_TOOL = {"type": "function", "function": {
    "name": "search_project_knowledge",
    "description": "Search the documents uploaded to this project's knowledge base and "
                   "return the most relevant passages, each headed by its source file "
                   "(e.g. `[report.pdf · chunk 3]`) so you can cite it. Use whenever the "
                   "user's question could be answered by the project's own documents — "
                   "prefer it over web search for project-specific facts.",
    "parameters": {"type": "object", "properties": {
        "question": {"type": "string",
                     "description": "What to look for, phrased as a full question."},
        "top_k": {"type": "integer",
                  "description": "How many passages to return (default 6)."}},
        "required": ["question"]}}}

PAST_CHATS_TOOL = {"type": "function", "function": {
    "name": "search_past_chats",
    "description": "Search the user's PAST conversations in this app by keyword and "
                   "return the matching chats (title, project, when, snippet). Use when "
                   "the user references earlier discussions ('as we discussed', 'the "
                   "plan from last week') that are not in the current conversation.",
    "parameters": {"type": "object", "properties": {
        "query": {"type": "string", "description": "Keywords to search for."}},
        "required": ["query"]}}}

ASK_USER_TOOL = {"type": "function", "function": {
    "name": "ask_user",
    "description": (
        "Ask the user 1-3 short structured clarifying questions when their intent is "
        "genuinely ambiguous AND the answer changes what you would produce. Each question "
        "offers 2-5 concise options; the user can also skip or reply freely. The turn ENDS "
        "after asking — the user's choices arrive as their next message. Use sparingly (at "
        "most once per request, before starting the work), never for things you can infer."),
    "parameters": {"type": "object", "properties": {
        "questions": {"type": "array", "description": "1-3 questions.",
            "items": {"type": "object", "properties": {
                "title": {"type": "string", "description": "The question itself."},
                "options": {"type": "array", "items": {"type": "string"},
                            "description": "2-5 short answer options."},
                "allow_other": {"type": "boolean",
                                "description": "Offer a freeform answer too (default true)."}},
                "required": ["title", "options"]}}},
        "required": ["questions"]}}}

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
    # Do NOT claim network isolation here: only the Docker engine runs with
    # --network none. The local fallback (used when Docker is absent) is
    # resource-limited but NOT network- or filesystem-isolated, so a false
    # "no network" guarantee would mislead both the model and the user.
    "name": "code_execution",
    "description": "Run a short Python 3 snippet in a restricted workspace and return "
                   "stdout/stderr. Use for ad-hoc computation, data shaping, and "
                   "verifying numbers. Use print(...) to produce output.",
    "parameters": {"type": "object", "properties": {
        "code": {"type": "string", "description": "Python source to execute."}},
        "required": ["code"]}}}

BASH_TOOL = {"type": "function", "function": {
    "name": "bash",
    "description": "Run ONE allowlisted shell command (ls, cat, grep, head, tail, "
                   "wc, echo, pwd, sort, uniq, cut …) in a confined workspace "
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

AUTHENTICATE_TOOL = {"type": "function", "function": {
    "name": "authenticate",
    "description": "Sign a connector into its provider when a tool fails with an "
                   "authentication/re-auth error (e.g. BigQuery/Google Cloud ADC saying "
                   "'Reauthentication is needed, run gcloud auth application-default "
                   "login', or GitHub/AWS). Runs the provider's official login CLI on "
                   "this machine and opens a browser for the user's consent — the user "
                   "only confirms in the browser, then you retry the original tool. The "
                   "app opens the sign-in URL automatically. Do NOT ask the user to run a "
                   "terminal command; call this instead.",
    "parameters": {"type": "object", "properties": {
        "provider": {"type": "string",
                     "description": "Which login to run: a flow id (gcloud-adc, "
                                    "gcloud-user, github, aws-sso) or a hint like "
                                    "'gcloud auth application-default login', 'bigquery', "
                                    "'github', 'aws sso'."}},
        "required": ["provider"]}}}

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

CODE_EXEC_SECTION = (
    "# RUNNING CODE\n"
    "You can actually EXECUTE Python with the `code_execution` tool — it runs in a "
    "sandboxed workspace and returns the REAL stdout/stderr. When the user asks you to "
    "run something, compute a result, process data, or produce a file, CALL "
    "`code_execution` and use its actual output. Files your code writes to the working "
    "directory (e.g. `df.to_csv('merged.csv')`) are saved and shown to the user as "
    "downloadable artifacts — so when they ask for a file, WRITE it to disk rather than "
    "printing it. NEVER say you ran a script, executed code, or generated a file unless a "
    "`code_execution` call actually did it, and never invent output, row counts, or file "
    "paths. If execution is unavailable or fails, say so plainly and provide the code."
)

def _knowledge_files_section(project_id: str | None, code_exec: bool) -> str | None:
    """List the project's uploaded knowledge files in the system prompt.

    Without this the model has no idea an upload exists: it won't reach for
    `search_project_knowledge`, and with filesystem/shell MCP connectors attached it
    goes hunting the disk for a plausible folder instead — hallucinated paths, then
    "where did you save the file?" back at the user."""
    if not project_id:
        return None
    from . import knowledge
    try:
        files = knowledge.list_project_files(project_id)
    except Exception:  # noqa: BLE001 - a listing failure must never kill the turn
        return None
    if not files:
        return None
    listing = "\n".join(f"- {f['name']} ({f['meta']})" for f in files[:50])
    more = f"\n(+{len(files) - 50} more)" if len(files) > 50 else ""
    section = (
        "# PROJECT FILES\n"
        "The user uploaded these files to this project's knowledge base:\n"
        f"{listing}{more}\n"
        "Search their content with `search_project_knowledge`. "
    )
    if code_exec:
        section += (
            "To work on the actual file (transform a CSV, parse a document…), exact "
            "copies are in your code-execution workspace under `knowledge/` — read "
            "them from there (e.g. `pd.read_csv('knowledge/data.csv')`) and write "
            "results to the working directory, never back into `knowledge/`. "
        )
    section += (
        "These are the only uploaded files and they live inside the app's own "
        "storage: never hunt for them with filesystem or shell tools, and never "
        "guess disk paths — if a file you need isn't listed here, say so."
    )
    return section


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
#
# Budgets are sized for agentic work: one iteration = one LLM round, and a real task
# (browse N pages, run SQL, iterate on errors) routinely needs 10-25 rounds. Budgets
# this small used to guillotine long turns mid-gathering; exhaustion now also degrades
# gracefully (wrap-up warning + forced no-tools synthesis below) so the cap is a cost
# ceiling, not a cliff.
EFFORT = {
    "Low":    {"steps": 4,  "plan": False, "verify": False, "temp": 0.0},
    "Medium": {"steps": 8,  "plan": False, "verify": False, "temp": 0.1},
    "High":   {"steps": 16, "plan": True,  "verify": False, "temp": 0.2},
    "Extra":  {"steps": 24, "plan": True,  "verify": False, "temp": 0.25},
    "Max":    {"steps": 32, "plan": True,  "verify": True,  "temp": 0.3},
}


def background_tool_flags(gated: bool) -> dict:
    """Tool posture for an UNATTENDED (Cowork/scheduled) run.

    The HITL approval gate only engages on interactive turns; a background run with
    the gate off would execute the destructive local tools (code_execution, bash,
    text_editor) with no confirmation, so any prompt-injected web/RAG/MCP content
    becomes unsupervised code execution. When the run is not gated we therefore
    withhold those tools and keep only the read/browse/orchestrate set. A caller that
    genuinely needs to build in the background must opt into the live HITL gate
    (approval="manual"), which sets ``gated=True`` and restores the full toolset.
    Propagates to subagents, which inherit the parent's code/file flags."""
    return {"web_search": True, "web_fetch": True, "artifacts": True,
            "memory": True, "subagents": True,
            "code_exec": gated, "bash": gated, "text_editor": gated}

# When this many tool rounds remain, tell the model — so it converges on an answer
# instead of being cut off mid-gathering. Without the warning the model has no idea a
# budget even exists and happily keeps opening new lines of investigation.
WRAP_UP_WARNING_AT = 2

_WRAP_UP_NOTE = (
    "[Turn budget: only {n} tool rounds remain.] Stop opening new lines of "
    "investigation. Finish at most the essential call(s), then write your final "
    "answer from what you already have.")

# Injected for the forced no-tools synthesis call when the budget is exhausted.
_FINALIZE_NOTE = (
    "You have used this turn's entire tool budget — no more tool calls are possible. "
    "Write your best FINAL answer now from everything gathered above: synthesize the "
    "findings, tool results, and partial data into a complete, well-organized "
    "response. If something important could not be checked, note it briefly at the "
    "end. Do not apologize about the budget; just answer.")

# Shown only if that synthesis call itself fails. Accurate advice: a LARGER budget
# (higher effort) helps; "lowering effort" (the old text) would shrink it further.
_STEP_LIMIT_FALLBACK = (
    "I hit this turn's step limit before I could finish. My work so far is shown "
    "above — say “continue” to pick up from there, or raise the effort "
    "level for a larger budget.")

# Escalating feedback for a tool call repeated verbatim after it already failed —
# without this a model can burn the whole budget re-issuing one broken call.
_REPEAT_FAIL_NOTE = (
    "\n\n[NOTE: this exact call already failed once with the same arguments. Do not "
    "repeat it verbatim — fix the arguments to match the error message, use a "
    "different tool, or continue without it.]")
_REPEAT_FAIL_STOP = (
    "\n\n[STOP: this identical call has now failed {n} times. It will not succeed. "
    "Do NOT call '{name}' with these arguments again this turn — change approach or "
    "answer with what you have.]")

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


# Backoff shape for transient LLM failures (esp. HTTP 429). We WAIT the amount the
# provider asks for via the `Retry-After` header when present — the single most
# effective thing for rate limits, since a per-minute quota needs the window to reset,
# not a sub-second retry — and otherwise fall back to jittered exponential backoff.
_RETRY_AFTER_CAP = 30.0   # never honor a Retry-After longer than this (avoid a long freeze)
_BACKOFF_CAP = 20.0       # ceiling for the exponential term
_BACKOFF_BASE = 0.75      # first exponential step
_STREAM_RETRIES = 4       # pre-first-chunk backoff retries on the streaming path


def _retry_after_seconds(exc: BaseException) -> float | None:
    """The server-suggested wait before retrying, parsed from the response's
    ``Retry-After`` header. Handles both the delta-seconds and the HTTP-date forms
    (OpenAI/Anthropic/most gateways send seconds). Returns None when absent."""
    resp = getattr(exc, "response", None)
    headers = getattr(resp, "headers", None)
    raw = None
    if headers is not None:
        try:
            raw = headers.get("retry-after") or headers.get("Retry-After")
        except Exception:  # noqa: BLE001 - not a mapping
            raw = None
    if not raw:
        return None
    raw = str(raw).strip()
    try:
        return max(0.0, float(raw))
    except ValueError:
        pass
    try:  # HTTP-date form, e.g. "Wed, 21 Oct 2026 07:28:00 GMT"
        import datetime as _dt
        from email.utils import parsedate_to_datetime
        when = parsedate_to_datetime(raw)
        if when is not None:
            now = _dt.datetime.now(tz=when.tzinfo)
            return max(0.0, (when - now).total_seconds())
    except Exception:  # noqa: BLE001 - unparseable header, fall back to backoff
        pass
    return None


def _backoff_delay(attempt: int, retry_after: float | None = None) -> float:
    """Seconds to sleep before the next attempt: honor the provider's Retry-After
    (capped), else jittered exponential backoff so retries don't align across callers."""
    if retry_after is not None:
        return min(retry_after, _RETRY_AFTER_CAP)
    base = min(_BACKOFF_CAP, _BACKOFF_BASE * (2 ** attempt))
    return base * (0.5 + random.random() * 0.5)  # 50–100% of the step


def _friendly_error(msg: str) -> str:
    """Turn a raw provider error into a user-actionable message. Rate limits are the
    common case worth explaining (the turn is retried first; this is only shown once
    the backoff budget is spent)."""
    low = (msg or "").lower()
    if "429" in low or "too many requests" in low or "rate limit" in low or "ratelimit" in low:
        return ("The model provider is rate-limiting requests right now (HTTP 429). "
                "Wait a few seconds and try again, or switch to a different "
                "model/provider in Settings.")
    return f"LLM call failed: {msg}"


async def _create_with_retry(llm, model, kw, retries: int = 2, base_delay: float = 0.5):
    """Call the model, retrying transient errors with backoff. Honors the provider's
    Retry-After header (falling back to jittered exponential backoff). Non-transient
    errors (and the final attempt) raise so the caller can fall back."""
    for attempt in range(retries + 1):
        try:
            return await asyncio.to_thread(llm.chat.completions.create, model=model, **kw)
        except Exception as e:
            if attempt < retries and _is_retryable(e):
                await asyncio.sleep(_backoff_delay(attempt, _retry_after_seconds(e)))
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

    def __init__(self, id, name, arguments, extra_content=None):
        self.id = id or ""
        self.type = "function"
        self.function = types.SimpleNamespace(name=name or "", arguments=arguments or "")
        # Google's compat endpoints attach the call's thought signature here
        # ({"google": {"thought_signature": …}}); Gemini 3 rejects the turn's next
        # request (400) unless it is replayed on the same call, so model_dump —
        # the exact dict run_turn replays as history — must carry it through.
        self.extra_content = extra_content

    def model_dump(self):
        d = {"id": self.id, "type": "function",
             "function": {"name": self.function.name,
                          "arguments": self.function.arguments}}
        if self.extra_content:
            d["extra_content"] = self.extra_content
        return d


async def _stream_chunks(llm, model, messages, tools, temperature, max_tokens,
                         extra: dict | None = None):
    """Bridge the blocking streaming `create()` into an async chunk generator by
    pumping chunks from a worker thread through a thread-safe queue.

    ``extra`` carries best-effort request params (stream_options for usage reporting,
    reasoning_effort for native thinking). Providers vary: if the request fails
    BEFORE the first chunk with extras attached, it is retried once without them, so
    an OpenAI-compatible endpoint that rejects unknown params never loses streaming."""
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue = asyncio.Queue()
    DONE = object()

    def _worker():
        base_kw = dict(messages=messages, temperature=temperature,
                       max_tokens=max_tokens, stream=True)
        if tools:
            base_kw["tools"] = tools
            base_kw["tool_choice"] = "auto"
        attempt = 0          # transient-failure backoff counter (pre-first-chunk only)
        drop_extras = False  # set once if the endpoint rejects the optional params
        try:
            while True:
                kw = dict(base_kw)
                if extra and not drop_extras:
                    kw.update(extra)
                got_chunk = False
                try:
                    for chunk in llm.chat.completions.create(model=model, **kw):
                        got_chunk = True
                        loop.call_soon_threadsafe(queue.put_nowait, chunk)
                    return
                except Exception as e:  # noqa: BLE001
                    if got_chunk:
                        raise  # a partial stream can't be safely replayed
                    # Transient (rate limit / 5xx / timeout) BEFORE any output: back off
                    # and retry, waiting the provider's Retry-After when present. This is
                    # the fix for a turn dying on a 429 after several tool rounds — the
                    # streaming path previously had NO rate-limit retry, so the first 429
                    # ended the turn.
                    if _is_retryable(e) and attempt < _STREAM_RETRIES:
                        time.sleep(_backoff_delay(attempt, _retry_after_seconds(e)))
                        attempt += 1
                        continue
                    # Not transient, but the optional params may be unsupported: retry once
                    # without them so an endpoint that rejects extras still streams.
                    if extra and not drop_extras:
                        drop_extras = True
                        continue
                    raise
        except Exception as e:  # noqa: BLE001
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


def _usage_of(obj) -> dict | None:
    """Provider-reported token usage from a chunk/response, or None. Best-effort:
    OpenAI-compatible providers attach {prompt_tokens, completion_tokens}."""
    u = getattr(obj, "usage", None)
    if u is None:
        return None
    p = getattr(u, "prompt_tokens", None)
    c = getattr(u, "completion_tokens", None)
    if p is None and c is None:
        return None
    return {"prompt_tokens": int(p or 0), "completion_tokens": int(c or 0)}


async def _stream_llm(llm, model, messages, tools=None, temperature=0.1,
                      max_tokens=4096, content_scope="answer", fallback_model=None,
                      reasoning: str | None = None):
    """Stream one LLM call. Yields {"type":"delta","scope":...,"text":...} for content
    (scope=content_scope) and reasoning (scope="think"), then a terminal
    {"__done__": {content, tool_calls, note, usage?, error?}}. Falls back to
    `fallback_model` (the provider's default) on a model error and to a non-streamed
    call if streaming itself is unavailable.

    ``reasoning`` requests NATIVE thinking ("low"/"medium"/"high") for models that
    support it; usage reporting is always requested. Both are best-effort — a
    provider that rejects the params gets one clean retry without them."""
    extra: dict = {"stream_options": {"include_usage": True}}
    if reasoning:
        extra["reasoning_effort"] = reasoning
    attempts = [model] if not fallback_model or model == fallback_model else [model, fallback_model]
    for ai, m in enumerate(attempts):
        content, tool_acc, started = [], {}, False
        reported_usage: dict | None = None
        art_streams: dict = {}          # per tool-call-index artifact content readers
        streamed_artifacts: set = set()  # ids emitted live (so completion only closes them)
        try:
            async for chunk in _stream_chunks(llm, m, messages, tools, temperature,
                                              max_tokens, extra=extra):
                u = _usage_of(chunk)
                if u:
                    reported_usage = u  # arrives on the final chunk
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
                                              {"id": "", "name": "", "arguments": "",
                                               "extra_content": None})
                    if getattr(tcd, "id", None):
                        acc["id"] = tcd.id
                    fn = getattr(tcd, "function", None)
                    if fn is not None:
                        if getattr(fn, "name", None):
                            acc["name"] = fn.name
                        if getattr(fn, "arguments", None):
                            acc["arguments"] += fn.arguments
                    # Gemini/Vertex thought signature (any delta of the call may
                    # carry it; direct attr or SDK model_extra, like reasoning_of).
                    ec = getattr(tcd, "extra_content", None) or \
                        (getattr(tcd, "model_extra", None) or {}).get("extra_content")
                    if ec:
                        acc["extra_content"] = ec
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
            tool_calls = [_ToolCallObj(a["id"] or f"call_{i}", a["name"], a["arguments"],
                                       extra_content=a.get("extra_content"))
                          for i, a in sorted(tool_acc.items())]
            note = (f"Model '{model}' is unavailable — fell back to {fallback_model}."
                    if m != model else None)
            yield {"__done__": {"content": "".join(content), "tool_calls": tool_calls,
                                "note": note, "streamed_artifacts": streamed_artifacts,
                                "usage": reported_usage}}
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
                                    "note": _friendly_error(note), "error": True}}
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
                                "tool_calls": list(msg.tool_calls or []), "note": note,
                                "usage": _usage_of(resp)}}
            return


# Friendly tool labels (Claude-style): name -> (running gerund, done past, icon).
TOOL_LABELS = {
    "ask_user":      ("Asking you a question", "Asked for your input", "question"),
    "search_project_knowledge": ("Searching project knowledge",
                                 "Searched project knowledge", "book"),
    "search_past_chats": ("Searching past chats", "Searched past chats", "search"),
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
    "authenticate":  ("Signing in connector", "Connector signed in", "key"),
}


def parse_questions(args: dict) -> list[dict]:
    """Validate + bound an ask_user payload into the wire shape the client renders.

    Caps: ≤3 questions, each with 2–5 non-empty string options; titles/options
    length-bounded. Returns [] when nothing valid survives (the caller then feeds an
    error back to the model instead of ending the turn)."""
    out: list[dict] = []
    for q in (args.get("questions") or [])[:3]:
        if not isinstance(q, dict):
            continue
        title = str(q.get("title") or "").strip()[:200]
        options = [str(o).strip()[:120] for o in (q.get("options") or [])
                   if str(o).strip()][:5]
        if not title or len(options) < 2:
            continue
        out.append({"title": title, "options": options,
                    "allow_other": bool(q.get("allow_other", True))})
    return out


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
    if name in ("search_schema", "search_project_knowledge"):
        return (args.get("question", "") or "")[:300]
    if name in ("web_search", "search_past_chats"):
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


def _exec_summary(res: dict) -> str:
    """One-line status for a code_execution outcome (engine + result + file count)."""
    if res.get("engine") in ("off", "docker-missing"):
        return (res.get("stderr") or "unavailable")[:120]
    n = len(res.get("files") or [])
    files = f" · {n} file{'' if n == 1 else 's'}" if n else ""
    if res.get("timed_out"):
        status = "timed out"
    elif res.get("ok"):
        status = "ran ok"
    else:
        status = f"exit {res.get('return_code')}"
    return f"{status}{files} · {res.get('engine')}"


async def _run_one_tool(name, args, tc_id, active_project, goal, top_k,
                        artifact_store=None, subagent=None, emit=None, ws=None) -> dict:
    """Execute ONE tool to completion and return a structured outcome (no UI events).
    Never raises — failures become {ok: False, ...} so the loop survives and the model
    can retry (Claude's is_error protocol, expressed in the tool-result string).

    ``emit(event)`` is an optional thread-safe sink for INTERIM UI events (used by
    code_execution to stream stdout/stderr live); it may be called from worker threads.

    ``ws`` is the per-turn workspace context built by run_turn when a workspace_root is
    attached (None otherwise). Harness tools are dispatched here, before the generic
    ladder below, so they share this function's never-raises contract."""
    try:
        if ws is not None:
            from .harness import workspace_fs as _wfs
            if name in _wfs.FILE_TOOL_NAMES:
                if name in ("edit_file", "write_file"):
                    # Snapshot the pre-edit bytes (or a not-yet-existing tombstone) BEFORE
                    # the mutation, keyed by this turn — the checkpoint restore point.
                    ws["ckpt"].snapshot_before_edit(
                        ws["ckpt_turn"], ws["root"], (args or {}).get("path", ""))
                out = _wfs.run_fs_tool(name, args, ws["root"], ws["read_paths"])
                if out.get("ok"):
                    result = (out.get("content")
                              or ("\n".join(out.get("paths", [])) if name == "glob" else None)
                              or ("\n".join(out.get("matches", [])) if name == "grep" else None)
                              or f"{name} ok: {out.get('path', '')}".strip())
                else:
                    result = f"ERROR: {out.get('error', 'failed')}"
                return {"id": tc_id, "name": name, "ok": out.get("ok", False), "result": result,
                        "summary": out.get("path", ""), "diff": out.get("diff"),
                        "paths": out.get("paths")}
            if name == "task_plan":
                out = ws["plan"].apply(args or {})
                return {"id": tc_id, "name": name, "ok": out.get("ok", False),
                        "result": ("plan updated" if out.get("ok")
                                   else f"ERROR: {out.get('error')}"),
                        "summary": "", "plan": ws["plan"].snapshot()}

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

        if name == "search_project_knowledge":
            from . import knowledge
            if not active_project:
                return {"id": tc_id, "name": name, "ok": False,
                        "result": "ERROR: no project is active for this conversation, so "
                                  "there is no knowledge base to search."}
            q = args.get("question", goal)
            try:
                k = max(1, min(int(args.get("top_k") or 6), 20))
            except (TypeError, ValueError):
                k = 6
            result = await asyncio.to_thread(
                knowledge.search_project_kb, active_project, q, k)
            if not result:
                return {"id": tc_id, "name": name, "ok": True,
                        "result": "No matching passages — the project knowledge base is "
                                  "empty or nothing matched. Answer from other sources "
                                  "and say the project documents didn't cover this.",
                        "summary": "no matches"}
            n = result.count("\n\n---\n\n") + 1
            return {"id": tc_id, "name": name, "ok": True, "result": result,
                    "summary": f"{n} passage{'' if n == 1 else 's'} · {len(result):,} chars"}

        if name == "search_past_chats":
            from . import conversations
            q = args.get("query", goal)
            hits = await asyncio.to_thread(conversations.search_conversations, q, 8)
            if not hits:
                return {"id": tc_id, "name": name, "ok": True,
                        "result": "No past conversations matched that query.",
                        "summary": "no matches"}
            lines = [
                f"- \"{h.get('title') or 'Untitled'}\" "
                f"({h.get('project_name', 'General')}, {h.get('updated_rel', '')}) — "
                f"matched in {h.get('matched_in', 'body')}: {h.get('snippet', '')}"
                for h in hits]
            result = "Past conversations matching the query:\n" + "\n".join(lines)
            return {"id": tc_id, "name": name, "ok": True, "result": result,
                    "summary": f"{len(hits)} chat{'' if len(hits) == 1 else 's'}"}

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
            # Pass the project's approved hosts so web_fetch can re-gate redirect
            # hops (the first-contact gate only OK'd the original host).
            approved = egress_policy.registry.approved_hosts(active_project)
            result, sources = await asyncio.to_thread(
                integrations.web_fetch, args.get("url", ""), approved)
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

            def _on_output(stream: str, text: str) -> None:
                if emit is not None:
                    emit({"type": "tool_output_delta", "id": tc_id,
                          "stream": stream, "text": text})

            res = await asyncio.to_thread(integrations.execute_code,
                                          args.get("code", ""), active_project, _on_output)
            result = integrations.format_execution_result(res)
            out = {"id": tc_id, "name": name, "ok": bool(res.get("ok")), "result": result,
                   "summary": _exec_summary(res), "exec_files": res.get("files", []),
                   "exec_project": active_project or "general"}
            if not res.get("ok"):
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

        if name == "authenticate":
            from . import auth_flows

            flow_id = auth_flows.match_flow(args.get("provider", ""))
            if not flow_id:
                opts = ", ".join(f["id"] for f in auth_flows.list_flows())
                return {"id": tc_id, "name": name, "ok": False,
                        "error": "unknown provider",
                        "result": f"ERROR: unknown auth provider. Options: {opts}. "
                                  "Pick one that matches the connector that needs re-auth."}

            def _auth_out(stream: str, text: str) -> None:
                if emit is not None:
                    emit({"type": "tool_output_delta", "id": tc_id,
                          "stream": stream, "text": text})

            def _auth_url(url: str) -> None:
                if emit is not None:
                    emit({"type": "auth_url", "id": tc_id, "provider": flow_id, "url": url})

            res = await asyncio.to_thread(auth_flows.run_flow, flow_id, _auth_out, _auth_url)
            ok = bool(res.get("ok"))
            detail = res.get("detail", "")
            # On success the dependent connectors were already reconnected (fresh creds),
            # so retry ONCE. Give the model an explicit off-ramp: if it STILL reports
            # re-auth, the cause is a Google org session policy on end-user creds, not a
            # stale token — repeating the sign-in would just loop forever.
            result = (f"{detail}. The affected connectors were reconnected with the fresh "
                      "credentials — retry the original tool ONCE now. If it STILL reports "
                      "that re-authentication is needed, STOP and do NOT sign in again: tell "
                      "the user their Google Cloud org likely enforces a re-auth/session "
                      "policy on end-user credentials, and the durable fix is a service "
                      "account (set GOOGLE_APPLICATION_CREDENTIALS for the connector)."
                      if ok else
                      f"ERROR: {detail}. Ask the user to complete the browser sign-in, "
                      "or tell them the required CLI isn't installed.")
            out = {"id": tc_id, "name": name, "ok": ok, "result": result,
                   "summary": detail[:200]}
            if not ok:
                out["error"] = detail
            return out

        if name in ("text_editor", "memory"):
            from . import integrations
            root = _tool_root(name, active_project)
            if name == "text_editor":
                result = await asyncio.to_thread(integrations.text_editor, args, root)
            else:
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


# Produced-file kind (from execute_code) -> artifact kind for in-panel display. Text
# files open as artifacts (the CSV etc.); images/binaries surface as downloads only.
_EXEC_ARTIFACT_KIND = {"csv": "csv", "markdown": "markdown", "html": "html",
                       "svg": "svg", "code": "code", "text": "code"}
_EXEC_MAX_FILE_ARTIFACTS = 4


def _exec_file_events(out: dict):
    """For a code_execution outcome: a `files` event listing everything produced, then
    an artifact (open/delta/close) for each small enough TEXT file so it opens in the
    side panel with Preview/Download (the CSV the user asked for)."""
    files = out.get("exec_files") or []
    if not files:
        return []
    evs = [{"type": "files", "id": out["id"], "project": out.get("exec_project", "general"),
            "items": [{"path": f["path"], "size": f["size"], "kind": f["kind"]}
                      for f in files]}]
    shown = 0
    for f in files:
        if shown >= _EXEC_MAX_FILE_ARTIFACTS or "text" not in f:
            continue
        kind = _EXEC_ARTIFACT_KIND.get(f["kind"])
        if not kind:
            continue
        lang = f["path"].rsplit(".", 1)[-1] if "." in f["path"] else ""
        aid = f"{out['id']}::{f['path']}"
        evs.append({"type": "artifact_open", "id": aid, "title": f["path"],
                    "kind": kind, "language": lang})
        evs.append({"type": "artifact_delta", "id": aid, "text": f["text"]})
        evs.append({"type": "artifact_close", "id": aid, "version": 1})
        shown += 1
    return evs


def _completion_events(out: dict, streamed_artifacts: set | None = None):
    """Derive the UI completion event(s) for a finished tool outcome (id-keyed). Artifacts
    whose content was already streamed live get only a final ``artifact_close`` (no repeat
    open + full-content delta)."""
    streamed_artifacts = streamed_artifacts or set()
    if not out.get("ok"):
        evs = [{"type": "tool_error", "id": out["id"], "name": out["name"],
                "text": out.get("error") or out.get("result", "Tool failed.")}]
        # A run that errored may still have written files (e.g. a chart, then crashed) —
        # surface them so the work isn't lost.
        if out.get("exec_files"):
            evs.extend(_exec_file_events(out))
        return evs
    evs = [{"type": "tool_result", "id": out["id"], "name": out["name"],
            "summary": out.get("summary", "")}]
    # Harness workspace tools additionally surface a dedicated tool_call marker (for the
    # desktop timeline), a file_diff (edit_file only — write_file has no "before"), and a
    # plan_update (task_plan) — on top of the generic tool_result above.
    if out.get("name") in ("read_file", "edit_file", "write_file", "glob", "grep", "task_plan"):
        evs.append({"type": "tool_call", "id": out["id"], "name": out["name"], "ok": True})
        if out.get("diff"):
            evs.append({"type": "file_diff", "id": out["id"], "diff": out["diff"]})
        if out.get("plan") is not None:
            evs.append({"type": "plan_update", "items": out["plan"]})
    if "table" in out:
        t = out["table"]
        evs.append({"type": "table", "id": out["id"], "columns": t["columns"],
                    "rows": t["rows"], "total": t["total"], "bytes": t["bytes"]})
    if out.get("sources"):
        evs.append({"type": "sources", "id": out["id"], "items": out["sources"]})
    if out.get("exec_files"):
        evs.extend(_exec_file_events(out))
    if out.get("artifact"):
        a = out["artifact"]
        if a["id"] not in streamed_artifacts:
            # Not streamed live → emit the whole artifact now (open + full content).
            evs.append({"type": "artifact_open", "id": a["id"], "title": a["title"],
                        "kind": a["kind"], "language": a.get("language", "")})
            evs.append({"type": "artifact_delta", "id": a["id"], "text": a["content"]})
        evs.append({"type": "artifact_close", "id": a["id"], "version": a["version"]})
    return evs


def _tool_root(kind: str, active_project: str | None):
    """The filesystem root for the text_editor / memory tools, jailed to a SANITIZED
    project slug (F-06). The raw active_project must never reach the Path join: an id like
    "C:/" or "../../x" would otherwise re-anchor the base and let the containment check
    pass against an attacker-chosen root. safe_project() is the same sanitizer the
    code-execution workspace already uses."""
    from . import integrations
    proj = integrations.safe_project(active_project)
    base = integrations.SANDBOX_ROOT if kind == "text_editor" else integrations.MEMORY_ROOT
    return base / proj


def _project_context(active_project: str | None,
                     instructions: str | None, memory: str | None) -> tuple[str, str]:
    """Fill project instructions + memory from the active project when a caller didn't
    pass them (F-19). Background/scheduled entry points supply neither, so without this
    an unattended run in a project would ignore that project's rules ("never touch
    production files") and saved context. Explicitly-passed values — including "" — are
    respected, so interactive and subagent callers are unaffected. A broken/absent
    project store (e.g. schema not yet created) degrades to empty context rather than
    crashing the turn — the same result as passing ""."""
    from . import projects
    if active_project:
        if instructions is None:
            try:
                instructions = projects.get_project_instructions(active_project)
            except Exception:
                instructions = ""
        if memory is None:
            try:
                memory = projects.get_project_memory(active_project)[0]
            except Exception:
                memory = ""
    return instructions or "", memory or ""


async def run_turn(goal: str, history: list[dict], active_project: str | None,
                   model: str, project_instructions: str | None = None,
                   top_k: int = 6,
                   web_search: bool = False, skill_instructions: str = "",
                   research: bool = False, extra_tools: list | None = None,
                   effort: str = "High", parallel: bool = True,
                   web_fetch: bool = False, code_exec: bool = False, bash: bool = False,
                   text_editor: bool = False, memory: bool = False,
                   provider: str | None = None, turn_id: str | None = None,
                   permission_mode: str | None = None, artifacts: bool = False,
                   user_profile: str = "", subagents: bool = False,
                   workspace_root: str | None = None, workspace_rules: dict | None = None,
                   project_memory: str | None = None, images: list[str] | None = None,
                   style: str = ""):
    """Drive one agent turn, yielding events. `history` is prior (role/content) turns.

    `turn_id` + `permission_mode` enable the interactive HITL gate: when set (and the
    mode is not "auto"), a sensitive tool call yields `approval_required` and the turn
    suspends until the reply endpoint resolves it (declined on timeout). With no
    turn_id or in "auto" mode, tools run without prompting (prior behavior).

    `provider` (optional) selects the model provider; otherwise it is inferred from a
    ``provider/model`` prefix on `model` or the configured default. BYOK: a missing
    key surfaces as a clean error event rather than crashing the stream.

    `images` (optional) are data-URI images attached to THIS user message; they ride
    the current turn as OpenAI-style multimodal content parts (history stays text).

    `project_instructions`/`project_memory` default to None → hydrated from the active
    project so background/scheduled runs honor project rules (F-19); pass "" to opt out.

    `workspace_root` (optional) attaches the harness coding layer: the five file tools
    (read_file/edit_file/write_file/glob/grep) + task_plan are registered, the workspace
    is described to the model via an env-context system-prompt section, and every tool
    call in the turn is first consulted against the harness permission rules (mode +
    allow/deny/ask) before falling through to the existing HITL gate above. `workspace_rules`
    is the caller-supplied ruleset (e.g. from the workspace registry); it is merged with the
    workspace's own `.claude/settings.json`. With `workspace_root=None` (the default) none
    of this activates and the turn behaves exactly as before the harness existed.
    """
    project_instructions, project_memory = _project_context(
        active_project, project_instructions, project_memory)
    cfg = EFFORT.get(effort, EFFORT["High"])
    temperature = cfg["temp"]
    steps = max(cfg["steps"], 24 if research else 0)
    # HITL gate is active only with a turn_id (a reply channel) and a non-auto mode.
    # Fail CLOSED when the request omits permission_mode: fall back to the user's
    # PERSISTED autonomy setting (defaults to "ask"), never config.PERMISSION_MODE
    # (which defaults to the ungated "auto"). Otherwise any non-desktop client that
    # simply doesn't send the field would silently bypass the approval gate.
    perm_mode = permission_mode or settings.get_settings().get("permission_mode") or "ask"
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
    if code_exec:
        extra_sections.append(CODE_EXEC_SECTION)
    if workspace_root:
        from .harness import env_context as _envctx
        extra_sections.append(_envctx.build(workspace_root))
    # Make uploads VISIBLE: list the project's knowledge files so the model reaches
    # for search_project_knowledge (or the workspace mirror) instead of hunting the
    # disk with whatever filesystem connector happens to be attached.
    kb_files = _knowledge_files_section(active_project, code_exec)
    if kb_files:
        extra_sections.append(kb_files)
    # Long-horizon context management: compact older turns so a long conversation
    # never overflows the model's context window (catalog handles a provider/ prefix).
    history, _ = context.compact_for_model(list(history or []), model)
    # Attached images: a vision-capable model gets them as native multimodal parts; a
    # text-only model (most open models) would SILENTLY ignore them and then hallucinate
    # "I can't see the image", so instead we describe them with a configured vision model
    # and inject that text (or a clear notice when no vision provider is available). This
    # makes attached images usable by ANY model, and the description flows to sub-agents.
    user_content: str | list = goal
    if images:
        if llm_catalog.supports_vision(model):
            user_content = [{"type": "text", "text": goal},
                            *({"type": "image_url", "image_url": {"url": u}}
                              for u in images)]
        else:
            note = await asyncio.to_thread(vision.image_context, images)
            user_content = f"{goal}\n\n{note}" if goal.strip() else note
    # Stamp the NEWEST user message with the current date/time. Injected at send
    # time only (never stored), so prior history stays byte-identical and the
    # system/history cache prefix survives — see prompts.temporal_context.
    stamp = prompts.temporal_context()
    if isinstance(user_content, list):
        user_content = [{"type": "text",
                         "text": f"{stamp}\n\n{user_content[0]['text']}"},
                        *user_content[1:]]
    else:
        user_content = f"{stamp}\n\n{user_content}"
    messages = [{"role": "system",
                 "content": prompts.build_system_prompt(
                     extra_sections=extra_sections or None, memory=memory,
                     user_profile=user_profile,
                     project_instructions=project_instructions,
                     project_memory=project_memory, style=style,
                     skill_instructions=skill_instructions, research=research)},
                *history, {"role": "user", "content": user_content}]
    tools = list(bigquery_tools.TOOL_SPECS) if bq_on else []
    # Project knowledge is a first-class capability of every project chat — NOT gated
    # on any connector. Uploaded documents are unreachable without this tool.
    if active_project:
        tools.append(PROJECT_KB_TOOL)
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
    # Harness workspace tools (only when a folder is attached): the five file tools +
    # task_plan, and a merged permission ruleset (the caller-supplied workspace_rules —
    # e.g. from the workspace registry — plus the workspace's own .claude/settings.json).
    # `ws` is the per-turn context threaded through dispatch (_run_one_tool) and the gate
    # below; it stays None for a non-workspace turn so both are no-ops there.
    ws = None
    ws_ruleset = None
    if workspace_root:
        from .harness import checkpoints as _ckpt
        from .harness import plan_tool as _plan
        from .harness import rules as _rules
        from .harness import workspace_fs as _wfs
        tools.extend(_wfs.FILE_TOOL_SPECS)
        tools.append(_plan.PLAN_TOOL_SPEC)
        _claude = _rules.load_claude_ruleset(workspace_root)
        _reg = workspace_rules or {}
        ws_ruleset = _rules.RuleSet(
            allow=list(_reg.get("allow", [])) + _claude.allow,
            deny=list(_reg.get("deny", [])) + _claude.deny,
            ask=list(_reg.get("ask", [])) + _claude.ask)
        ws = {"root": workspace_root, "read_paths": set(), "plan": _plan.Plan(),
              "ckpt": _ckpt.CheckpointStore(config.REPO_ROOT / "checkpoints"),
              "ckpt_turn": turn_id or "adhoc"}
    # Structured clarifying questions need a live user to answer them: only offer the
    # tool on interactive turns (turn_id present). Cowork/scheduler/subagent runs pass
    # no turn_id and must never stall waiting for input.
    if turn_id:
        tools.append(ASK_USER_TOOL)
        # Memory: recall past conversations ("search and reference chats"). Local,
        # read-only, settings-gated; interactive chats only — background runs have
        # no business trawling the user's history.
        if settings.get_settings().get("memory_search", True):
            tools.append(PAST_CHATS_TOOL)
        # Connector sign-in also needs a live user (to consent in the browser). Always
        # HITL-gated (sensitive), so it can never run a host login CLI silently.
        if auth_flows.enabled():
            tools.append(AUTHENTICATE_TOOL)
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

    # Native reasoning (P1-1): a model that supports provider-side thinking gets it,
    # mapped from the effort level; the harness's plan/verify passes still apply.
    native_reasoning = ({"Low": "low", "Medium": "medium"}.get(effort, "high")
                        if llm_catalog.supports_reasoning(model) else None)

    # Provider-reported token usage, folded across EVERY round of the turn (planning,
    # each tool round, verify, finalize). `last_prompt` is the final context size for
    # the meter; `input` sums what was actually billed across rounds.
    reported = {"input": 0, "output": 0, "last_prompt": 0, "rounds": 0}

    def _fold_usage(done: dict) -> None:
        u = done.get("usage")
        if u:
            reported["input"] += u.get("prompt_tokens", 0)
            reported["output"] += u.get("completion_tokens", 0)
            reported["last_prompt"] = u.get("prompt_tokens", 0)
            reported["rounds"] += 1

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
        _fold_usage(done)
        plan = (done.get("content") or "").strip()
        if plan:
            messages.append({"role": "assistant", "content": f"My plan: {plan}"})

    # A delegated subtask runs a fresh, isolated agent turn: same model/provider/effort,
    # tool CAPABILITIES, and PROJECT CONTEXT as the parent, but auto-permission (no HITL to
    # answer), no UI artifacts, and no further nesting (subagents=False). Only its final
    # answer flows back to the parent. Subagent turns are deliberately NOT Opik-traced
    # individually: the parent turn's spawn_subagent tool span already covers them.
    subagent_calls = 0

    async def _run_subagent(sub_prompt: str, description: str) -> dict:
        # Fan-out cap: each subagent is a full nested turn, so unbounded delegation is
        # the main way an autonomous run multiplies spend. Past the cap, tell the model
        # to finish the work itself instead of spawning more.
        nonlocal subagent_calls
        subagent_calls += 1
        if config.MAX_SUBAGENTS_PER_TURN and subagent_calls > config.MAX_SUBAGENTS_PER_TURN:
            return {"ok": False,
                    "result": (f"ERROR: the subagent limit ({config.MAX_SUBAGENTS_PER_TURN}) "
                               "for this turn has been reached. Do the remaining work "
                               "yourself instead of delegating it.")}
        fold = events.AnswerAccumulator()
        tools_used: list[str] = []
        err: str | None = None
        # Inherit the parent's project context so delegated work obeys the SAME project
        # rules ("respond in French", "use TypeScript", "never touch production") and sees
        # the same memory. These are the parent's already-hydrated values; active_project
        # carries the knowledge base (search_project_knowledge + the uploaded-file listing).
        # Previously the subagent passed project_instructions="" and silently dropped them.
        async for ev in run_turn(
                sub_prompt, [], active_project, model,
                project_instructions=project_instructions, project_memory=project_memory,
                top_k=top_k, web_search=web_search, research=research, web_fetch=web_fetch,
                code_exec=code_exec, bash=bash, text_editor=text_editor, memory=memory,
                artifacts=False, effort=effort, parallel=parallel, provider=provider,
                permission_mode="auto", subagents=False):
            fold.feed(ev)
            t = ev.get("type")
            if t == "tool":
                tools_used.append(ev.get("name", ""))
            elif t == "error":
                err = ev.get("text", "subagent error")
        if err:
            return {"ok": False, "error": err,
                    "result": f"The subagent failed: {err}. Proceed without it, or retry "
                              "with a clearer, more self-contained prompt."}
        answer = fold.text.strip() or "(the subagent produced no answer)"
        used = ", ".join(dict.fromkeys(x for x in tools_used if x)) or "no tools"
        return {"ok": True, "result": answer,
                "summary": f"{(description or 'subtask')[:60]} · used {used} · "
                           f"{len(answer):,} chars"}

    subagent_runner = _run_subagent if subagents else None

    # ---- Main tool-calling loop (streamed) ----
    final_text = None
    answer_shown = False
    out_parts: list[str] = []  # accumulated generated text, for the usage estimate
    # (name, canonical-args) -> observed failure count, for the repeat-fail breaker.
    fail_counts: dict[tuple[str, str], int] = {}
    warned = False  # wrap-up note is injected at most once per turn
    for step_i in range(steps):
        yield {"type": "answer_open"}
        done = {}
        async for ev in _stream_llm(llm, model, messages, tools, temperature, 4096,
                                    content_scope="answer", fallback_model=fallback_model,
                                    reasoning=native_reasoning):
            if "__done__" in ev:
                done = ev["__done__"]
            else:
                yield ev
        _fold_usage(done)
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
        sig_by_id: dict[str, tuple[str, str]] = {}  # tc.id -> repeat-fail signature
        for tc in tool_calls:
            raw_args = tc.function.arguments or ""
            name = tc.function.name
            try:
                args = json.loads(raw_args or "{}")
                # Canonicalize so key order / whitespace don't hide a verbatim repeat.
                sig_by_id[tc.id] = (name, json.dumps(args, sort_keys=True, default=str))
            except Exception:
                # Unparseable arguments: the raw string is the identity — two DIFFERENT
                # malformed payloads must not collapse into one breaker counter.
                args = {}
                sig_by_id[tc.id] = (name, raw_args)
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
            # ask_user: surface a structured question card and END the turn — the user's
            # choices arrive as their next message (§5.1). Needs no permission (it only
            # asks), so it is handled before the plan-mode/HITL gates. An invalid payload
            # feeds an error back to the model instead of ending the turn.
            if name == "ask_user":
                qs = parse_questions(args)
                if not qs:
                    yield {"type": "tool_error", "id": tc.id, "name": name,
                           "text": "Invalid ask_user payload."}
                    blocked_outcomes.append({"id": tc.id, "name": name, "ok": False,
                        "result": ("ERROR: ask_user requires questions=[{title, options[2-5]}]. "
                                   "Fix the payload and call it again, or proceed without asking.")})
                    continue
                yield {"type": "tool_result", "id": tc.id, "name": name,
                       "summary": "Waiting for your answer"}
                yield {"type": "question", "id": tc.id, "questions": qs}
                return
            # Plan mode: `exit_plan_mode` presents the plan for approval; approving LEAVES
            # plan mode (the rest of this turn runs under the normal HITL gate). Every other
            # state-changing tool is blocked until then.
            if plan_mode and name == "exit_plan_mode":
                yield {"type": "approval_required", "turn_id": turn_id, "id": tc.id,
                       "name": name, "input": _tool_input(name, args)}
                permissions.registry.describe(
                    turn_id, tc.id, tool_name=name, args=args
                )
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
                    "skip_breaker": True,  # a mode rule, not a fixable tool failure
                    "result": (f"BLOCKED: '{name}' cannot run in PLAN MODE. Do not modify "
                               "anything yet. Finish researching read-only, then call "
                               "exit_plan_mode with your plan for the user to approve.")})
                continue
            # First-contact domain approval: web_fetch is the one tool whose
            # destination is model-chosen, so the FIRST reach to a new host is
            # gated on the user (and remembered per project). Search/MCP/
            # connectors hit fixed/configured hosts -> outbound_host is None.
            # web_fetch is "safe", so the sensitive-tool gate below never fires
            # for it; this is its gate.
            egress_host = egress_policy.outbound_host(name, args)
            # True once the domain gate LIVE-prompts and gets approval for this
            # call, so the sensitive-tool gate below won't re-prompt the same
            # tc.id — strict/plan modes gate *every* tool (incl. "safe" ones),
            # and a second wait() on an already-resolved tc.id would just time
            # out and wrongly report "Declined".
            domain_gate_prompted = False
            if egress_host is not None:
                if egress_policy.registry.is_approved(active_project, egress_host):
                    observability.audit({"event": "egress_decision", "tool": name,
                        "host": egress_host, "project": active_project,
                        "decision": "cached", "turn": turn_id})
                elif not gate_on:
                    # auto mode (or no turn): don't prompt, but record + audit.
                    egress_policy.registry.approve(active_project, egress_host)
                    observability.audit({"event": "egress_decision", "tool": name,
                        "host": egress_host, "project": active_project,
                        "decision": "auto", "turn": turn_id})
                else:
                    yield {"type": "approval_required", "turn_id": turn_id, "id": tc.id,
                           "name": name, "input": _tool_input(name, args),
                           "reason": f"first contact with {egress_host}"}
                    permissions.registry.describe(
                        turn_id, tc.id, tool_name=name, args=args)
                    approved = await permissions.registry.wait(
                        turn_id, tc.id, config.PERMISSION_TIMEOUT_SEC)
                    observability.audit({"event": "egress_decision", "tool": name,
                        "host": egress_host, "project": active_project,
                        "decision": "approved" if approved else "denied", "turn": turn_id})
                    if not approved:
                        yield {"type": "tool_error", "id": tc.id, "name": name,
                               "text": f"Not approved to reach {egress_host}."}
                        blocked_outcomes.append({"id": tc.id, "name": name, "ok": False,
                            "skip_breaker": True,  # a user decision, not a fixable failure
                            "result": (f"The user did NOT approve reaching '{egress_host}'. "
                                       "Do not retry web_fetch for that host; continue "
                                       "without it or ask how to proceed.")})
                        continue
                    egress_policy.registry.approve(active_project, egress_host)
                    domain_gate_prompted = True
            # Harness workspace rule gate: for a workspace turn, allow/deny/ask rules
            # (workspace_rules + the workspace's .claude/settings.json, merged into
            # ws_ruleset above) and the active permission mode are consulted BEFORE the
            # existing HITL gate. 'deny' blocks the call outright (a mode/rule decision,
            # not a fixable failure); 'allow' runs it immediately, skipping the HITL
            # prompt below entirely; 'ask' changes nothing — it falls through to the
            # existing gate, which decides using its own sensitivity list.
            if workspace_root:
                from .harness import rules as _rules
                _decision = _rules.gate(name, args, perm_mode, ws_ruleset)
                if _decision == "deny":
                    yield {"type": "tool_error", "id": tc.id, "name": name,
                           "text": f"Blocked by permission rules/mode for {name}."}
                    blocked_outcomes.append({"id": tc.id, "name": name, "ok": False,
                        "skip_breaker": True,
                        "result": f"BLOCKED: '{name}' denied by the active permission mode/rules."})
                    continue
                if _decision == "allow":
                    calls.append((tc.id, name, args))
                    continue
                # _decision == "ask" -> fall through to the existing HITL prompt below
            # HITL: suspend for a user decision before running a sensitive tool. Pass
            # args so a memory *mutation* (create/delete/…) is gated even though the
            # memory tool is otherwise read-only "safe".
            if gate_on and not domain_gate_prompted and permissions.requires_approval(name, perm_mode, args):
                yield {"type": "approval_required", "turn_id": turn_id, "id": tc.id,
                       "name": name, "input": _tool_input(name, args)}
                permissions.registry.describe(
                    turn_id, tc.id, tool_name=name, args=args
                )
                approved = await permissions.registry.wait(
                    turn_id, tc.id, config.PERMISSION_TIMEOUT_SEC)
                if not approved:
                    yield {"type": "tool_error", "id": tc.id, "name": name,
                           "text": "Declined by the user."}
                    # skip_breaker: a decline is the USER's decision, not a tool failure
                    # — the repeat-fail breaker's "fix the arguments and retry" advice
                    # would contradict the decline message.
                    blocked_outcomes.append({"id": tc.id, "name": name, "ok": False,
                        "skip_breaker": True,
                        "result": (f"The user DECLINED to run '{name}'. Do not retry it; "
                                   "continue without it or ask how to proceed.")})
                    continue
            calls.append((tc.id, name, args))

        streamed = done.get("streamed_artifacts") or set()
        outcomes = []
        if calls:
            loop = asyncio.get_running_loop()
            # Interim UI events (live code_execution output) flow through this queue;
            # `_emit` is thread-safe so execute_code's reader threads can push deltas.
            # `interim`/`loop` are bound as defaults so the closures capture THIS
            # iteration's queue (they are created and fully drained within it).
            interim: asyncio.Queue = asyncio.Queue()

            def _emit(ev, _q=interim, _loop=loop):
                _loop.call_soon_threadsafe(_q.put_nowait, ev)

            async def _runner(i, n, a, _q=interim):
                # Always enqueue a done sentinel — even if _run_one_tool escapes with an
                # unexpected error — so the drain loop below can never hang waiting on it.
                try:
                    out = await _run_one_tool(n, a, i, active_project, goal, top_k,
                                              artifact_store, subagent=subagent_runner,
                                              emit=_emit, ws=ws)
                except BaseException as e:  # noqa: BLE001 - convert to a tool failure, never hang
                    out = {"id": i, "name": n, "ok": False, "error": str(e)[:300],
                           "result": f"ERROR: {n} crashed: {str(e)[:200]}"}
                _q.put_nowait(("__done__", out))

            # One concurrent group when parallel; otherwise one-call groups run in order.
            groups = [calls] if (parallel and len(calls) > 1) else [[c] for c in calls]
            for group in groups:
                tasks = [asyncio.create_task(_runner(*c)) for c in group]
                pending = len(group)
                while pending:
                    item = await interim.get()
                    if isinstance(item, tuple) and item and item[0] == "__done__":
                        out = item[1]
                        outcomes.append(out)
                        for ev in _completion_events(out, streamed):
                            yield ev
                        # A checkpoint is the file's pre-mutation restore point, already
                        # captured by snapshot_before_edit inside _run_one_tool; the event
                        # just tells the UI a rewind point now exists for this turn.
                        if (workspace_root and out.get("ok")
                                and out.get("name") in ("edit_file", "write_file")):
                            yield {"type": "checkpoint", "turn_id": turn_id}
                        pending -= 1
                    else:
                        yield item  # live tool_output_delta
                await asyncio.gather(*tasks)

        # Feed every tool result back to the model, one message per tool_call_id
        # (executed + any blocked-by-enablement calls, preserving the model's order).
        by_id = {o["id"]: o for o in (outcomes + blocked_outcomes)}
        for tc in tool_calls:
            if tc.id not in by_id:
                continue
            out = by_id[tc.id]
            # Cap any single oversized tool output so it can't overflow the window.
            result = context.truncate_tool_result(out["result"])
            if not out.get("ok") and not out.get("skip_breaker"):
                # Repeat-fail breaker: the SAME call failing again gets escalating
                # feedback, so one broken call can't silently eat the whole budget
                # (seen in the wild: 7 identical invalid Click calls in one turn).
                sig = sig_by_id.get(tc.id)
                if sig is not None:
                    n = fail_counts[sig] = fail_counts.get(sig, 0) + 1
                    if n == 2:
                        result += _REPEAT_FAIL_NOTE
                    elif n >= 3:
                        result += _REPEAT_FAIL_STOP.format(n=n, name=out["name"])
            messages.append({"role": "tool", "tool_call_id": tc.id, "content": result})
        # Landing gear: tell the model the budget is nearly spent so it converges
        # instead of being cut off mid-gathering. <= plus the flag (not ==) so a
        # blank-answer round at the threshold can't silently skip the warning.
        if not warned and steps - step_i - 1 <= WRAP_UP_WARNING_AT:
            warned = True
            messages.append({"role": "user",
                             "content": _WRAP_UP_NOTE.format(n=steps - step_i - 1)})
        # Runaway backstop (cost ceiling): once the turn's reported tokens cross the
        # budget, stop opening new work. Breaking here — after a full round — lands on
        # the same finalize synthesis as step-cap exhaustion, so the turn still ends with
        # the model's answer, not a hard cut. reported tokens are best-effort, so this is
        # a no-op for providers that don't report usage (the step cap still bounds them).
        if config.TURN_TOKEN_BUDGET and \
                reported["input"] + reported["output"] >= config.TURN_TOKEN_BUDGET:
            break

    if final_text is None:
        # Budget exhausted mid-work. Don't throw the gathered material away: make one
        # last NO-TOOLS call so the model synthesizes its best answer from everything
        # above. A long agentic turn should always end with the model's answer, never
        # a harness error — the canned text below is only the double-failure fallback.
        messages.append({"role": "user", "content": _FINALIZE_NOTE})
        yield {"type": "answer_open"}
        done = {}
        async for ev in _stream_llm(llm, model, messages, None, temperature, 4096,
                                    content_scope="answer", fallback_model=fallback_model):
            if "__done__" in ev:
                done = ev["__done__"]
            else:
                yield ev
        _fold_usage(done)
        # Keep whatever synthesis arrived — even a partial one cut short by a stream
        # error is the model's actual answer and beats the canned fallback.
        wrap = (done.get("content") or "").strip()
        if wrap:
            final_text = wrap
            out_parts.append(wrap)
        else:
            final_text = _STEP_LIMIT_FALLBACK
            yield {"type": "delta", "scope": "answer", "text": final_text}
        answer_shown = True

    # ---- Verification pass (Max): self-critique and refine, streamed ----
    if cfg["verify"] and not answer_shown:
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
        _fold_usage(done)
        vtext = _strip_answer_label((done.get("content") or "").strip())
        if vtext:
            final_text = vtext
            out_parts.append(vtext)
        else:  # verify produced nothing — show the draft as the answer
            yield {"type": "delta", "scope": "answer", "text": final_text}
        answer_shown = True

    # ---- Usage / cost meter (one event at the end of a successful turn) ----
    yield usage.build_usage(model, messages, "".join(out_parts),
                            reported=reported if reported["rounds"] else None)
