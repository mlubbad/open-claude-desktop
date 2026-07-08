// Pure helpers for exporting artifacts: filenames, MIME types, and a printable
// HTML document (used by "Print as PDF"). Framework-free and unit-tested.

import type { ArtifactDoc } from "./transcript";

// Kinds rendered in a sandboxed iframe (they produce visual output).
export const IFRAME_KINDS = new Set(["html", "svg", "mermaid", "react"]);

// Whether an artifact has a working Preview. iframe kinds render live; markdown
// renders formatted; anything else with source shows as syntax-highlighted code —
// so every artifact is previewable (matching the reference's always-on eye toggle).
export function isPreviewable(kind: string): boolean {
  return IFRAME_KINDS.has(kind) || kind === "markdown" || kind === "code" ||
    kind === "csv" || kind === "" || kind === "text";
}

// The markdown fed to the in-panel renderer for non-iframe kinds: a markdown
// artifact renders as-is; any other text/code artifact is wrapped in a fenced block
// (tagged with its language) so rehype-highlight syntax-colours it. iframe kinds
// have no in-panel markdown, so they return "".
export function previewMarkdown(kind: string, content: string, language = ""): string {
  if (IFRAME_KINDS.has(kind)) return "";
  if (kind === "markdown") return content;
  // Pick a fence the body can't contain so a code sample with ``` doesn't break out.
  const fence = content.includes("```") ? "~~~" : "```";
  return `${fence}${language}\n${content}\n${fence}`;
}

export function slug(s: string): string {
  return s.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "") || "artifact";
}

export function ext(kind: string, language = ""): string {
  const map: Record<string, string> = {
    html: "html",
    svg: "svg",
    mermaid: "mmd",
    react: "jsx",
    markdown: "md",
    csv: "csv",
    code: language || "txt",
  };
  return map[kind] ?? "txt";
}

export function mime(kind: string): string {
  const map: Record<string, string> = {
    html: "text/html",
    svg: "image/svg+xml",
    markdown: "text/markdown",
    mermaid: "text/plain",
    react: "text/plain",
    csv: "text/csv",
    code: "text/plain",
  };
  return map[kind] ?? "text/plain";
}

// Parse CSV text into { columns, rows } for the artifact table preview. Handles quoted
// fields, escaped quotes ("") and commas/newlines inside quotes. Framework-free + tested;
// the first row is treated as the header.
export function parseCsv(text: string): { columns: string[]; rows: string[][] } {
  const records: string[][] = [];
  let field = "";
  let row: string[] = [];
  let inQuotes = false;
  const src = text.replace(/\r\n?/g, "\n");
  for (let i = 0; i < src.length; i++) {
    const c = src[i];
    if (inQuotes) {
      if (c === '"') {
        if (src[i + 1] === '"') {
          field += '"';
          i++;
        } else {
          inQuotes = false;
        }
      } else {
        field += c;
      }
    } else if (c === '"') {
      inQuotes = true;
    } else if (c === ",") {
      row.push(field);
      field = "";
    } else if (c === "\n") {
      row.push(field);
      records.push(row);
      field = "";
      row = [];
    } else {
      field += c;
    }
  }
  // Flush the trailing field/row unless the text ended on a clean newline.
  if (field !== "" || row.length > 0) {
    row.push(field);
    records.push(row);
  }
  if (records.length === 0) return { columns: [], rows: [] };
  const [header, ...body] = records;
  return { columns: header, rows: body };
}

export function filename(doc: Pick<ArtifactDoc, "title" | "kind" | "language">): string {
  return `${slug(doc.title)}.${ext(doc.kind, doc.language)}`;
}

// The short type tag shown next to the title ("· MD", "· HTML"…).
export function typeTag(kind: string, language = ""): string {
  return ext(kind, language).toUpperCase();
}

function escapeHtml(s: string): string {
  return s.replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" })[c] ?? c);
}

// A standalone printable document for "Print as PDF". Previewable artifacts print
// their rendered form (the caller passes the sandbox srcDoc); text artifacts print
// as a titled monospace sheet.
export function printableHtml(title: string, content: string, renderedSrcDoc?: string): string {
  if (renderedSrcDoc) return renderedSrcDoc;
  return (
    `<!doctype html><html><head><meta charset="utf-8"><title>${escapeHtml(title)}</title>` +
    `<style>body{font-family:system-ui,sans-serif;margin:32px;color:#222}h1{font-size:18px}` +
    `pre{white-space:pre-wrap;font-family:ui-monospace,monospace;font-size:12px;line-height:1.55}</style>` +
    `</head><body><h1>${escapeHtml(title)}</h1><pre>${escapeHtml(content)}</pre></body></html>`
  );
}
