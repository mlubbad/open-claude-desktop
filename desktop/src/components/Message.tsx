import { useState } from "react";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";

import type { AssistantMessage, Block, ThinkingBlock, ToolCard, UserMessage } from "../state/transcript";

export function UserBubble({ msg }: { msg: UserMessage }) {
  return (
    <div className="msg user">
      <div className="bubble">{msg.text}</div>
    </div>
  );
}

export function AssistantBubble({ msg }: { msg: AssistantMessage }) {
  return (
    <div className="msg assistant">
      {msg.blocks.map((b, i) => (
        <BlockView key={i} block={b} />
      ))}
    </div>
  );
}

function BlockView({ block }: { block: Block }) {
  if (block.kind === "thinking") return <Thinking block={block} />;
  if (block.kind === "tool") return <Tool block={block} />;
  return (
    <div className="answer">
      <Markdown remarkPlugins={[remarkGfm]}>{block.text}</Markdown>
    </div>
  );
}

function Thinking({ block }: { block: ThinkingBlock }) {
  const [open, setOpen] = useState(block.streaming);
  const label = block.streaming
    ? "Thinking…"
    : `Thought${block.elapsed ? ` for ${block.elapsed}s` : ""}`;
  return (
    <div className={`thinking ${block.streaming ? "streaming" : ""}`}>
      <button className="thinking-toggle" onClick={() => setOpen((o) => !o)}>
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
        : block.status === "error"
          ? block.labelDone
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
