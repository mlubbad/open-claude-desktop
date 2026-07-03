// Serialize the desktop transcript to/from the backend's stored shape.
//
// The backend stores a conversation transcript as a list of {role, content, kind}
// (a JSON column). We preserve the rich assistant transcript (thinking, tools,
// answer) losslessly by JSON-encoding the block list into `content` with
// kind="blocks"; plain assistant strings (kind != "blocks") load as a single
// answer block for back-compat.

import type { AssistantMessage, Block, Message } from "./transcript";

export interface StoredMessage {
  role: string;
  content: string;
  kind: string;
}

export function toBackend(messages: Message[]): StoredMessage[] {
  return messages.map((m) => {
    if (m.role === "user") {
      return { role: "user", content: m.text, kind: "user" };
    }
    // Drop still-streaming flags so stored blocks are final.
    const blocks = m.blocks.map(finalizeBlock);
    return { role: "assistant", content: JSON.stringify(blocks), kind: "blocks" };
  });
}

export function fromBackend(stored: StoredMessage[]): Message[] {
  return stored.map((s): Message => {
    if (s.role === "user") {
      return { role: "user", text: s.content };
    }
    if (s.kind === "blocks") {
      try {
        const blocks = JSON.parse(s.content) as Block[];
        if (Array.isArray(blocks)) return { role: "assistant", blocks };
      } catch {
        /* fall through to plain text */
      }
    }
    // Back-compat: a plain assistant string becomes one finalized answer block.
    return {
      role: "assistant",
      blocks: [{ kind: "answer", text: s.content, streaming: false }],
    };
  });
}

// Text preview of a conversation's first user message (for titles/lists).
export function firstUserText(messages: Message[]): string {
  const u = messages.find((m) => m.role === "user");
  return u && u.role === "user" ? u.text : "";
}

function finalizeBlock(b: Block): Block {
  if (b.kind === "answer" || b.kind === "thinking") return { ...b, streaming: false };
  return b;
}

// Narrowing helper kept for symmetry / external use.
export function isAssistant(m: Message): m is AssistantMessage {
  return m.role === "assistant";
}
