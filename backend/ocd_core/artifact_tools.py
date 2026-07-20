"""Artifacts connector — the agent-facing surface (Phase 3).

Lets the model produce standalone, renderable documents (HTML pages, React
components, SVG, Mermaid diagrams, code files, long Markdown) that the client shows
in a side panel and can iterate on. The tool specs, the system-prompt guidance, and
the per-turn artifact store live here; the agent loop emits `artifact_open` /
`artifact_delta` / `artifact_close` events from a tool outcome (see agent._completion_events).
"""
from __future__ import annotations

import re

KINDS = ("html", "react", "svg", "mermaid", "code", "markdown", "csv")

# A whole-content markdown fence: models routinely wrap tool-call content in
# ```lang … ``` even when told not to; renderers must see raw source (a fenced
# mermaid body renders as "Syntax error in text"). Greedy body → the closer is the
# LAST fence line, so a markdown document containing inner fences survives intact.
_FENCE_RE = re.compile(r"\A```[ \t]*[\w+.-]*[ \t]*\r?\n(.*?)(?:\r?\n)?```[ \t]*\Z", re.S)


def strip_code_fence(content: str) -> str:
    """Unwrap ``content`` when the ENTIRE payload is one fenced code block."""
    m = _FENCE_RE.match(content.strip())
    return m.group(1) if m else content

CREATE_ARTIFACT_TOOL = {"type": "function", "function": {
    "name": "create_artifact",
    "description": "Create a standalone, renderable document shown in the side panel: a "
                   "complete HTML page, a React component, an SVG, a Mermaid diagram, a "
                   "code file, a long Markdown document, or a CSV data table (kind=csv, "
                   "shown as a downloadable table). Use this for substantial, "
                   "self-contained content the user will view, copy, download, or iterate "
                   "on — NOT for short inline snippets. Provide the FULL content.",
    "parameters": {"type": "object", "properties": {
        "title": {"type": "string", "description": "Short human title for the artifact."},
        "kind": {"type": "string", "enum": list(KINDS),
                 "description": "The artifact type. Use 'csv' for tabular/spreadsheet data "
                                "(comma-separated; it renders as a table and downloads as a "
                                ".csv the user can open in Excel/Sheets)."},
        "language": {"type": "string",
                     "description": "For kind=code, the language (e.g. python, ts)."},
        "content": {"type": "string", "description": "The COMPLETE artifact content."}},
        "required": ["title", "kind", "content"]}}}

UPDATE_ARTIFACT_TOOL = {"type": "function", "function": {
    "name": "update_artifact",
    "description": "Revise an existing artifact, producing a new version. For small "
                   "changes (fewer than ~20 lines and fewer than 5 locations), send "
                   "old_str/new_str — old_str must match the current content EXACTLY "
                   "and appear EXACTLY once. For larger or structural changes, send "
                   "the FULL updated content instead (a complete rewrite, not a diff).",
    "parameters": {"type": "object", "properties": {
        "id": {"type": "string", "description": "The artifact id to update."},
        "title": {"type": "string", "description": "Optional new title."},
        "old_str": {"type": "string",
                    "description": "Exact existing text to replace; must appear exactly "
                                   "once in the artifact."},
        "new_str": {"type": "string",
                    "description": "Replacement text for old_str (empty deletes it)."},
        "content": {"type": "string",
                    "description": "The COMPLETE updated content (full rewrite). "
                                   "Overrides old_str/new_str if both are sent."}},
        "required": ["id"]}}}

TOOL_SPECS = [CREATE_ARTIFACT_TOOL, UPDATE_ARTIFACT_TOOL]
TOOL_NAMES = frozenset(t["function"]["name"] for t in TOOL_SPECS)


def system_prompt_section() -> str:
    return """# ARTIFACTS
Create an artifact (`create_artifact`) for substantial, self-contained content the user \
will view, run, edit, or reuse outside the chat: content over ~20 lines or 1500 \
characters — a complete HTML page, a React component, an SVG or Mermaid diagram, a code \
file, a structured Markdown document, or a data table. Keep your chat message a brief \
description; the artifact opens in a side panel. Do NOT create artifacts for short \
snippets, explanations, or one-off answers — put those inline. At most one artifact per \
message unless the user asks for more.

Artifact content rules:
- Send the COMPLETE raw source as `content`. NEVER wrap it in markdown code fences \
(no ```); the panel renders raw source, and a fenced body breaks the preview.
- mermaid: raw Mermaid source only. Double-quote EVERY label/title in xychart, pie and \
similar diagrams — unquoted non-ASCII (Arabic, accents, CJK) or parenthesized labels are \
parser errors. Labels can never contain a double quote; use ' instead.
- react: one component with a default export and no required props. Style with Tailwind \
utility classes. Available imports (nothing else is installed): react, recharts, \
lucide-react, d3, lodash, papaparse, xlsx, mathjs, chart.js, tone, three. NEVER use \
localStorage/sessionStorage — the sandbox blocks browser storage; keep state in React \
state or variables.
- html: one single self-contained file (inline CSS/JS). External scripts/styles only \
from cdnjs.cloudflare.com or cdn.jsdelivr.net. Browser storage is blocked here too.
- svg: set a viewBox rather than fixed width/height.
- code: include the `language` argument.

To revise an artifact, call `update_artifact` with its id: send `old_str`/`new_str` for \
small edits (old_str must match exactly and appear exactly once) or the complete new \
`content` for larger rewrites.

When the user asks for a FILE, spreadsheet, or CSV of data, you MUST deliver it as an \
artifact or a produced file — never paste the rows into your chat reply and never tell \
the user to copy-paste text into an editor. For tabular data use `create_artifact` with \
kind=csv (comma-separated; it renders as a table and downloads as a .csv the user can \
open in Excel/Sheets). If the data must be COMPUTED, merged, or read from files first — \
or the user wants a real xlsx, docx, pptx, or pdf — use the `code_execution` tool to \
build it and write the file (pandas/openpyxl `df.to_excel('out.xlsx')`, python-docx, \
python-pptx, reportlab, `df.to_csv('out.csv', index=False)`); files it writes are shown \
to the user as downloads."""


def create(args: dict, store: dict, artifact_id: str | None = None) -> dict:
    """Create an artifact in the per-turn store and return its document. ``artifact_id``
    lets the caller pin the id (e.g. the streaming tool-call id) so a live-streamed
    artifact and its final record share one id; defaults to a per-store counter."""
    aid = artifact_id or f"art{len(store) + 1}"
    kind = args.get("kind", "markdown")
    if kind not in KINDS:
        kind = "markdown"
    doc = {
        "id": aid,
        "title": (args.get("title") or "Untitled").strip(),
        "kind": kind,
        "language": (args.get("language") or "").strip(),
        "content": strip_code_fence(args.get("content") or ""),
        "version": 1,
    }
    store[aid] = doc
    return dict(doc)


def update(args: dict, store: dict) -> tuple[dict | None, str | None]:
    """Revise an existing artifact (new version). Returns (doc, error).

    Two modes, mirroring Claude's artifacts contract: full ``content`` (rewrite), or
    ``old_str``/``new_str`` (targeted replacement, exactly-once). Errors leave the
    stored document untouched so the model can retry.
    """
    aid = (args.get("id") or "").strip()
    doc = store.get(aid)
    if not doc:
        return None, f"No artifact with id '{aid}'. Create one first."
    if args.get("content") is not None:
        content = strip_code_fence(args["content"])
    elif args.get("old_str") is not None:
        old, new = args["old_str"], args.get("new_str") or ""
        n = doc["content"].count(old)
        if n == 0:
            return None, (f"old_str not found in artifact '{aid}'. Send the exact "
                          "existing text, or the full replacement content.")
        if n > 1:
            return None, (f"old_str appears {n} times in artifact '{aid}' — it must be "
                          "unique. Include more surrounding context.")
        content = doc["content"].replace(old, new, 1)
    else:
        return None, ("Provide either old_str/new_str (targeted change) or content "
                      "(full rewrite).")
    doc["content"] = content
    if args.get("title"):
        doc["title"] = args["title"].strip()
    doc["version"] += 1
    return dict(doc), None
