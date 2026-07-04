// Pure helpers for composer file attachments. Text files are read client-side and
// inlined into the outgoing message as fenced context blocks — model-agnostic (no
// vision needed), so it works with any BYOK model.

export interface Attachment {
  name: string;
  content: string;
}

// Per-file cap so a huge paste can't blow the request (the backend also truncates
// tool/context, but bound it early on the client too).
export const MAX_ATTACH_CHARS = 100_000;

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
