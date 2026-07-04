// Pure serializers for exporting a conversation transcript. Framework-free and
// deterministic so they can be unit-tested and reused by any UI. Markdown is for
// humans; JSON is the loss-tolerant structural export.

import type { ArtifactDoc, Block, Message } from "./transcript";

function artifactFence(doc: ArtifactDoc): string {
  const lang = doc.kind === "code" ? doc.language || "" : doc.kind;
  return `**Artifact — ${doc.title}** (v${doc.version || 1})\n\n\`\`\`${lang}\n${doc.content}\n\`\`\``;
}

function blockToMarkdown(b: Block): string | null {
  switch (b.kind) {
    case "answer":
      return b.text.trim() || null;
    case "thinking":
      // Keep reasoning available but collapsed so exports read like the final answer.
      return b.text.trim() ? `<details><summary>Thinking</summary>\n\n${b.text.trim()}\n\n</details>` : null;
    case "tool": {
      const status = b.status === "error" ? ` — error: ${b.error ?? ""}` : "";
      const detail = b.summary ? `: ${b.summary}` : "";
      return `> 🔧 ${b.labelDone || b.name}${detail}${status}`.trim();
    }
    case "artifact":
      return artifactFence(b.doc);
    default:
      return null;
  }
}

// Render a transcript to Markdown with "## You" / "## Assistant" turn headings.
export function toMarkdown(messages: Message[], title = "Conversation"): string {
  const lines: string[] = [`# ${title}`, ""];
  for (const m of messages) {
    if (m.role === "user") {
      lines.push("## You", "", m.text.trim(), "");
    } else {
      const parts = m.blocks.map(blockToMarkdown).filter((p): p is string => !!p);
      if (parts.length) lines.push("## Assistant", "", parts.join("\n\n"), "");
    }
  }
  return lines.join("\n").replace(/\n{3,}/g, "\n\n").trimEnd() + "\n";
}

// Structural JSON export: the message list plus a small envelope.
export function toJSON(messages: Message[], title = "Conversation"): string {
  return JSON.stringify({ title, exported_format: "ocd.transcript.v1", messages }, null, 2);
}

// Filesystem-safe slug for a download filename.
export function exportSlug(title: string): string {
  return (title || "conversation").toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "") || "conversation";
}
