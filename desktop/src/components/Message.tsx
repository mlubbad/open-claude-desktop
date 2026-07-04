import { type ReactNode, useRef, useState } from "react";
import Markdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";

import { Icon } from "./Icon";
import {
  type ArtifactBlock,
  answerText,
  type AssistantMessage,
  type Block,
  type ThinkingBlock,
  type ToolCard,
  type UserMessage,
} from "../state/transcript";

export function UserBubble({
  msg,
  onEdit,
}: {
  msg: UserMessage;
  onEdit?: (text: string) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(msg.text);

  if (editing) {
    return (
      <div className="msg user">
        <div className="bubble editing">
          <textarea value={draft} autoFocus rows={Math.min(8, draft.split("\n").length + 1)}
                    onChange={(e) => setDraft(e.target.value)} />
          <div className="edit-actions">
            <button onClick={() => { setDraft(msg.text); setEditing(false); }}>Cancel</button>
            <button className="primary"
                    onClick={() => { setEditing(false); if (draft.trim() && draft !== msg.text) onEdit?.(draft); }}>
              Save &amp; submit
            </button>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="msg user">
      <div className="bubble">{msg.text}</div>
      {onEdit && (
        <button className="msg-action user-edit" title="Edit" onClick={() => { setDraft(msg.text); setEditing(true); }}>
          Edit
        </button>
      )}
    </div>
  );
}

export function AssistantBubble({
  msg,
  isLast,
  busy,
  onRetry,
  onOpenArtifact,
}: {
  msg: AssistantMessage;
  isLast: boolean;
  busy: boolean;
  onRetry?: () => void;
  onOpenArtifact?: (id: string) => void;
}) {
  const answer = answerText(msg);
  const streaming = msg.blocks.some((b) => (b.kind === "answer" || b.kind === "thinking") && b.streaming);
  return (
    <div className="msg assistant">
      {msg.blocks.map((b, i) => (
        <BlockView key={i} block={b} onOpenArtifact={onOpenArtifact} />
      ))}
      {!streaming && answer && (
        <div className={`msg-actions ${isLast ? "pinned" : ""}`}>
          <CopyButton getText={() => answer} label="Copy" />
          {isLast && onRetry && (
            <button className="msg-action" onClick={onRetry} disabled={busy} title="Regenerate">
              <Icon name="retry" size={13} /> Retry
            </button>
          )}
        </div>
      )}
    </div>
  );
}

function CopyButton({ getText, label }: { getText: () => string; label: string }) {
  const [copied, setCopied] = useState(false);
  function copy() {
    void navigator.clipboard?.writeText(getText());
    setCopied(true);
    setTimeout(() => setCopied(false), 1200);
  }
  return (
    <button className="msg-action" onClick={copy} title={label}>
      {copied ? "Copied" : label}
    </button>
  );
}

const mdComponents: Components = {
  pre({ children }) {
    return <CodeBlock>{children}</CodeBlock>;
  },
};

function CodeBlock({ children }: { children?: ReactNode }) {
  const ref = useRef<HTMLPreElement>(null);
  const [copied, setCopied] = useState(false);
  function copy() {
    const text = ref.current?.innerText ?? "";
    void navigator.clipboard?.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 1200);
  }
  return (
    <div className="codeblock">
      <button className="code-copy" onClick={copy}>
        {copied ? "Copied" : "Copy"}
      </button>
      <pre ref={ref}>{children}</pre>
    </div>
  );
}

function BlockView({ block, onOpenArtifact }: { block: Block; onOpenArtifact?: (id: string) => void }) {
  if (block.kind === "thinking") return <Thinking block={block} />;
  if (block.kind === "tool") return <Tool block={block} />;
  if (block.kind === "artifact") return <ArtifactCard block={block} onOpen={onOpenArtifact} />;
  return (
    <div className="answer">
      <Markdown remarkPlugins={[remarkGfm]} components={mdComponents}>
        {block.text}
      </Markdown>
    </div>
  );
}

function ArtifactCard({ block, onOpen }: { block: ArtifactBlock; onOpen?: (id: string) => void }) {
  const { doc } = block;
  return (
    <button className="artifact-card" onClick={() => onOpen?.(doc.id)}>
      <span className="artifact-card-icon">▧</span>
      <span className="artifact-card-meta">
        <span className="artifact-card-title">{doc.title}</span>
        <span className="artifact-card-kind">
          {doc.kind}
          {doc.version > 1 ? ` · v${doc.version}` : ""}
        </span>
      </span>
      <span className="artifact-card-open">Open ›</span>
    </button>
  );
}

function Thinking({ block }: { block: ThinkingBlock }) {
  const [open, setOpen] = useState(block.streaming);
  const label = block.streaming ? "Thinking…" : `Thought${block.elapsed ? ` for ${block.elapsed}s` : ""}`;
  return (
    <div className={`thinking ${block.streaming ? "streaming" : ""}`}>
      <button className="thinking-toggle" aria-expanded={open} onClick={() => setOpen((o) => !o)}>
        <span className="chev">{open ? "▾" : "▸"}</span> {label}
      </button>
      {open && <div className="thinking-body">{block.text}</div>}
    </div>
  );
}

function Tool({ block }: { block: ToolCard }) {
  const label =
    block.status === "running"
      ? block.labelRunning
      : block.status === "awaiting_approval"
        ? `${block.labelRunning} — awaiting approval`
        : block.labelDone;
  return (
    <div className={`tool ${block.status}`}>
      <div className="tool-head">
        <span className="tool-name">{label}</span>
        {block.summary && <span className="tool-summary">{block.summary}</span>}
      </div>
      {block.input && <pre className="tool-input">{block.input}</pre>}
      {block.error && <div className="tool-error">{block.error}</div>}
      {block.table && <ResultTable columns={block.table.columns} rows={block.table.rows} />}
      {block.sources && block.sources.length > 0 && (
        <ul className="sources">
          {block.sources.map((s, i) => (
            <li key={i}>
              <a href={s.url} target="_blank" rel="noreferrer">
                {s.title || s.domain || s.url}
              </a>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function ResultTable({ columns, rows }: { columns: string[]; rows: Record<string, unknown>[] }) {
  return (
    <div className="table-scroll">
      <table>
        <thead>
          <tr>
            {columns.map((c) => (
              <th key={c}>{c}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.slice(0, 50).map((r, i) => (
            <tr key={i}>
              {columns.map((c) => (
                <td key={c}>{String(r[c] ?? "")}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
