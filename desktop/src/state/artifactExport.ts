// Pure helpers for exporting artifacts: filenames, MIME types, and a printable
// HTML document (used by "Print as PDF"). Framework-free and unit-tested.

import type { ArtifactDoc } from "./transcript";

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
    code: "text/plain",
  };
  return map[kind] ?? "text/plain";
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
