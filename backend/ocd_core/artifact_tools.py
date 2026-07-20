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
    "description": "Revise an existing artifact, producing a new version. Provide the FULL "
                   "updated content (not a diff).",
    "parameters": {"type": "object", "properties": {
        "id": {"type": "string", "description": "The artifact id to update."},
        "title": {"type": "string", "description": "Optional new title."},
        "content": {"type": "string", "description": "The COMPLETE updated content."}},
        "required": ["id", "content"]}}}

TOOL_SPECS = [CREATE_ARTIFACT_TOOL, UPDATE_ARTIFACT_TOOL]
TOOL_NAMES = frozenset(t["function"]["name"] for t in TOOL_SPECS)


def system_prompt_section() -> str:
    return """# ARTIFACTS
When you produce substantial, self-contained content the user will view, run, copy, \
download, or iterate on — a complete HTML page, a React component, an SVG or Mermaid \
diagram, a code file, a long Markdown document, or a DATA TABLE / spreadsheet — call \
`create_artifact` with the FULL content instead of putting it inline in your reply. Keep \
your chat message a brief description; the artifact opens in a side panel. To revise it, \
call `update_artifact` with the artifact id and the complete new content. Use short inline \
code blocks (not artifacts) for small snippets.

When the user asks for a FILE, spreadsheet, or CSV of data, you MUST deliver it as an \
artifact — never paste the rows into your chat reply and never tell the user to \
copy-paste the text into a text editor and save it. For tabular data use \
`create_artifact` with kind=csv (comma-separated; it renders as a table and downloads as \
a .csv). If the data must be COMPUTED, merged, or read from files first, use the \
`code_execution` tool to build it and write the file (e.g. `df.to_csv('out.csv', \
index=False)`) — the file it writes is shown to the user as a downloadable artifact."""


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
    """Revise an existing artifact (new version). Returns (doc, error)."""
    aid = (args.get("id") or "").strip()
    doc = store.get(aid)
    if not doc:
        return None, f"No artifact with id '{aid}'. Create one first."
    if args.get("content") is not None:
        doc["content"] = strip_code_fence(args["content"])
    if args.get("title"):
        doc["title"] = args["title"].strip()
    doc["version"] += 1
    return dict(doc), None
