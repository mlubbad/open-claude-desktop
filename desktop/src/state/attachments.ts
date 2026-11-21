// Pure helpers for composer file attachments. Text files are read client-side and
// inlined into the outgoing message as fenced context blocks — model-agnostic (no
// vision needed), so it works with any BYOK model.

export interface Attachment {
  name: string;
  content: string;
}

// Image attachments travel separately from text: as data-URI vision input on the
// turn request, not inlined into the goal text.
export interface ImageAttachment {
  name: string;
  dataUrl: string;
}

// Per-file cap so a huge paste can't blow the request (the backend also truncates
// tool/context, but bound it early on the client too).
export const MAX_ATTACH_CHARS = 100_000;

// Bounds mirrored by the backend schema (MAX_IMAGES / MAX_IMAGE_CHARS): at most 6
// images, ~6 MB each before base64 expansion.
export const MAX_IMAGES = 6;
export const MAX_IMAGE_BYTES = 6_000_000;

export function isImageFile(f: { type: string }): boolean {
  return f.type.startsWith("image/");
}

// Enforce the image caps on an incoming batch: keeps the first MAX_IMAGES that fit
// the size bound, given how many are already attached. Pure — the caller reads files.
export function admitImages<T extends { size: number }>(existing: number, files: T[]): T[] {
  return files.filter((f) => f.size <= MAX_IMAGE_BYTES).slice(0, Math.max(0, MAX_IMAGES - existing));
}

export function clampContent(content: string, max: number = MAX_ATTACH_CHARS): string {
  return content.length <= max ? content : content.slice(0, max) + "\n… [truncated]";
}

// Pick a fenced-code language hint from a filename extension (best-effort, cosmetic).
export function fenceLang(name: string): string {
  const ext = (name.split(".").pop() ?? "").toLowerCase();
  const map: Record<string, string> = {
    md: "markdown", py: "python", ts: "ts", tsx: "tsx", js: "js", jsx: "jsx",
    json: "json", csv: "csv", html: "html", css: "css", yaml: "yaml", yml: "yaml",
    sql: "sql", sh: "bash", log: "",
  };
  return map[ext] ?? "";
}

export function formatAttachments(atts: Attachment[]): string {
  return atts
    .map((a) => `Attached file: ${a.name}\n\n\`\`\`${fenceLang(a.name)}\n${a.content}\n\`\`\``)
    .join("\n\n");
}

// Combine the typed message with any attachments into the final goal text.
export function withAttachments(text: string, atts: Attachment[]): string {
  if (!atts.length) return text;
  const block = formatAttachments(atts);
  return text.trim() ? `${text.trim()}\n\n${block}` : block;
}

// Inverse of withAttachments, for display: split a stored user message back into the
// typed body and its trailing attachment blocks so the transcript can render compact
// file chips instead of walls of pasted text. Best-effort — anything that doesn't
// match the exact serialized shape stays in the body untouched.
const ATTACH_BLOCK = /(?:^|\n\n)Attached file: ([^\n]+)\n\n```[^\n]*\n([\s\S]*?)\n```(?=\n\n|$)/g;

export function parseAttachments(text: string): { body: string; files: Attachment[] } {
  const files: Attachment[] = [];
  let end = text.length;
  // Collect matches, then only accept the run of blocks that reaches the end of the
  // message (attachments are always appended after the typed body).
  const matches = [...text.matchAll(ATTACH_BLOCK)];
  for (let i = matches.length - 1; i >= 0; i--) {
    const m = matches[i];
    const start = m.index ?? 0;
    if (start + m[0].length === end) {
      files.unshift({ name: m[1], content: m[2] });
      end = start;
    } else {
      break; // a non-trailing block means everything before it is prose
    }
  }
  if (!files.length) return { body: text, files };
  return { body: text.slice(0, end).trim(), files };
}
