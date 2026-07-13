import { memo, type ReactNode, useEffect, useRef, useState } from "react";
import Markdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";

import { downloadWorkspaceFile } from "../api/client";
import type { ProducedFile } from "../api/events";
import { openExternal } from "../platform";
import { type Attachment, parseAttachments } from "../state/attachments";
import { Icon } from "./Icon";
import { QuestionCard } from "./QuestionCard";
import {
  type ArtifactBlock,
  answerText,
  type AssistantMessage,
  type Block,
  type QuestionBlock,
  type ThinkingBlock,
  type ToolCard,
  type UserMessage,
} from "../state/transcript";

function UserBubbleImpl({
  msg,
  onEdit,
  onBranch,
}: {
  msg: UserMessage;
  onEdit?: (text: string) => void;
  onBranch?: () => void;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(msg.text);
  // Attached files travel inlined in the message text; render them back as compact
  // chips so a pasted file doesn't wall-of-text the transcript. Editing still edits
  // the raw wire text (attachments included).
  const { body, files } = parseAttachments(msg.text);

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
      {(msg.images?.length ?? 0) > 0 && (
        <div className="user-images">
          {msg.images!.map((src, i) => (
            <img key={i} src={src} alt={`Attached image ${i + 1}`} className="user-image" />
          ))}
        </div>
      )}
      {files.length > 0 && (
        <div className="user-files">
          {files.map((f, i) => (
            <FileChip key={i} file={f} />
          ))}
        </div>
      )}
      {body && <div className="bubble">{body}</div>}
      {(onEdit || onBranch) && (
        <div className="user-actions">
          {onEdit && (
            <button className="msg-action user-edit" title="Edit message" aria-label="Edit message"
                    onClick={() => { setDraft(msg.text); setEditing(true); }}>
              <Icon name="pencil" size={13} />
            </button>
          )}
          {onBranch && (
            <button className="msg-action user-branch" title="Branch from here"
                    aria-label="Branch conversation from this message" onClick={onBranch}>
              <Icon name="branch" size={13} />
            </button>
          )}
        </div>
      )}
    </div>
  );
}

// Memoized so a streaming turn (which re-renders the whole transcript on every token)
// doesn't re-render every prior user bubble. The parent's onEdit is a fresh closure each
// render, so we compare only the data: the message identity and whether editing is
// offered. A retained onEdit closure stays correct — bubbles are keyed per conversation
// and its captured index is stable for an existing message.
export const UserBubble = memo(
  UserBubbleImpl,
  (a, b) => a.msg === b.msg && !!a.onEdit === !!b.onEdit && !!a.onBranch === !!b.onBranch,
);

// A pasted/attached file on a user turn: name + type badge, expandable to inspect
// the content that was sent.
function FileChip({ file }: { file: Attachment }) {
  const [open, setOpen] = useState(false);
  const ext = (file.name.split(".").pop() ?? "").toUpperCase();
  return (
    <div className="user-file">
      <button
        className="user-file-head"
        aria-expanded={open}
        title={open ? "Hide content" : "Show content"}
        onClick={() => setOpen((o) => !o)}
      >
        <span className="user-file-icon" aria-hidden="true"><Icon name="file" size={15} /></span>
        <span className="user-file-name">{file.name}</span>
        <span className="user-file-badge">{ext || "PASTED"}</span>
      </button>
      {open && <pre className="user-file-body">{file.content}</pre>}
    </div>
  );
}

function AssistantBubbleImpl({
  msg,
  isLast,
  busy,
  onRetry,
  onOpenArtifact,
  onAnswerQuestion,
  onFeedback,
  onBranch,
}: {
  msg: AssistantMessage;
  isLast: boolean;
  busy: boolean;
  onRetry?: () => void;
  onOpenArtifact?: (id: string) => void;
  onAnswerQuestion?: (id: string, text: string) => void;
  onFeedback?: () => void;
  onBranch?: () => void;
}) {
  const answer = answerText(msg);
  const streaming = msg.blocks.some((b) => (b.kind === "answer" || b.kind === "thinking") && b.streaming);
  // Local, per-message feedback marker (visual only; nothing is sent anywhere).
  // A regenerated reply is new content, so streaming clears any prior vote.
  const [vote, setVote] = useState<"up" | "down" | null>(null);
  useEffect(() => {
    if (streaming) setVote(null);
  }, [streaming]);
  return (
    <div className="msg assistant">
      {msg.blocks.map((b, i) => (
        <BlockView key={i} block={b} busy={busy} onOpenArtifact={onOpenArtifact} onAnswerQuestion={onAnswerQuestion} />
      ))}
      {!streaming && answer && (
        <div className={`msg-actions ${isLast ? "pinned" : ""}`}>
          <CopyButton getText={() => answer} />
          <button
            className={`msg-action ${vote === "up" ? "voted" : ""}`}
            title="Good response"
            aria-label="Good response"
            aria-pressed={vote === "up"}
            onClick={() => setVote((v) => (v === "up" ? null : "up"))}
          >
            <Icon name="thumb-up" size={14} />
          </button>
          <button
            className={`msg-action ${vote === "down" ? "voted" : ""}`}
            title="Bad response"
            aria-label="Bad response"
            aria-pressed={vote === "down"}
            onClick={() => {
              setVote((v) => (v === "down" ? null : "down"));
              onFeedback?.();
            }}
          >
            <Icon name="thumb-down" size={14} />
          </button>
          {isLast && onRetry && (
            <button className="msg-action" onClick={onRetry} disabled={busy}
                    title="Retry" aria-label="Regenerate response">
              <Icon name="retry" size={14} />
            </button>
          )}
          {onBranch && (
            <button className="msg-action" onClick={onBranch}
                    title="Branch from here" aria-label="Branch conversation from this message">
              <Icon name="branch" size={14} />
            </button>
          )}
        </div>
      )}
    </div>
  );
}

// Memoized on the data (message identity, isLast, busy). This is the big win: during
// streaming only the LAST message's `msg` changes reference, so earlier assistant
// bubbles — each an expensive Markdown re-parse — skip re-rendering entirely. The
// action callbacks are hook-stable or per-conversation-scoped, so ignoring their
// identity in the comparison is safe.
export const AssistantBubble = memo(
  AssistantBubbleImpl,
  (a, b) => a.msg === b.msg && a.isLast === b.isLast && a.busy === b.busy,
);

function CopyButton({ getText }: { getText: () => string }) {
  const [copied, setCopied] = useState(false);
  function copy() {
    void navigator.clipboard?.writeText(getText());
    setCopied(true);
    setTimeout(() => setCopied(false), 1200);
  }
  return (
    <button className="msg-action" onClick={copy} title={copied ? "Copied" : "Copy"}
            aria-label={copied ? "Copied" : "Copy response"}>
      <Icon name={copied ? "check" : "copy"} size={14} />
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

function BlockView({
  block,
  busy,
  onOpenArtifact,
  onAnswerQuestion,
}: {
  block: Block;
  busy: boolean;
  onOpenArtifact?: (id: string) => void;
  onAnswerQuestion?: (id: string, text: string) => void;
}) {
  if (block.kind === "thinking") return <Thinking block={block} />;
  if (block.kind === "tool") return <Tool block={block} />;
  if (block.kind === "artifact") return <ArtifactCard block={block} onOpen={onOpenArtifact} />;
  if (block.kind === "question")
    return <QuestionCard block={block as QuestionBlock} busy={busy} onSubmit={onAnswerQuestion ?? (() => {})} />;
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
      <span className="artifact-card-icon" aria-hidden="true">
        <Icon name="file" size={18} />
      </span>
      <span className="artifact-card-meta">
        <span className="artifact-card-title">{doc.title}</span>
        <span className="artifact-card-kind">
          {doc.kind}
          {doc.version > 1 ? ` · v${doc.version}` : ""}
        </span>
      </span>
      <span className="artifact-card-open">Open</span>
    </button>
  );
}

// Show at most this many characters of a finished thought before folding the rest
// behind "Show more" (streaming thoughts always show everything as they arrive).
const THINKING_FOLD = 700;

function Thinking({ block }: { block: ThinkingBlock }) {
  const [open, setOpen] = useState(block.streaming);
  const [showAll, setShowAll] = useState(false);
  const label = block.streaming ? "Thinking…" : `Thought${block.elapsed ? ` for ${block.elapsed}s` : ""}`;
  const long = !block.streaming && block.text.length > THINKING_FOLD;
  const text = long && !showAll ? block.text.slice(0, THINKING_FOLD).trimEnd() + "…" : block.text;
  return (
    <div className={`thinking ${block.streaming ? "streaming" : ""}`}>
      <button className="thinking-toggle" aria-expanded={open} onClick={() => setOpen((o) => !o)}>
        <span className="thinking-ic" aria-hidden="true"><Icon name="clock" size={13} /></span>
        {label}
        <span className={`chev ${open ? "" : "chev-collapsed"}`} aria-hidden="true">
          <Icon name="chev-down" size={12} />
        </span>
      </button>
      {open && block.text && (
        <div className="thinking-body">
          {text}
          {long && (
            <button className="thinking-more" onClick={() => setShowAll((s) => !s)}>
              {showAll ? "Show less" : "Show more"}
            </button>
          )}
        </div>
      )}
      {!block.streaming && open && (
        <div className="thinking-done">
          <Icon name="check" size={13} /> Done
        </div>
      )}
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
      {block.output && <pre className="tool-output">{block.output}</pre>}
      {block.authUrl && block.status === "running" && (
        <div className="tool-auth">
          <span className="tool-auth-msg">Complete sign-in in your browser, then this continues automatically.</span>
          <button className="tool-auth-open" onClick={() => void openExternal(block.authUrl!)}>
            <Icon name="cloud-up" size={13} /> Open sign-in
          </button>
        </div>
      )}
      {block.files && block.files.length > 0 && (
        <ProducedFiles files={block.files} project={block.filesProject} />
      )}
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

// Human-readable byte size for a produced file chip.
function fmtSize(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / (1024 * 1024)).toFixed(1)} MB`;
}

// The files a code_execution run wrote to the workspace, each with a Download button
// (authenticated blob fetch). The primary text file (e.g. the CSV) also opens as an
// artifact in the side panel; this list makes every output — including images — savable.
function ProducedFiles({ files, project }: { files: ProducedFile[]; project?: string }) {
  return (
    <div className="tool-files">
      <div className="tool-files-label">
        {files.length} file{files.length === 1 ? "" : "s"} produced
      </div>
      {files.map((f) => (
        <div className="tool-file" key={f.path}>
          <span className="tool-file-icon" aria-hidden="true">
            <Icon name="file" size={15} />
          </span>
          <span className="tool-file-name">{f.path}</span>
          <span className="tool-file-size">{fmtSize(f.size)}</span>
          <button
            className="tool-file-dl"
            title={`Download ${f.path}`}
            aria-label={`Download ${f.path}`}
            onClick={() => void downloadWorkspaceFile(f.path, project)}
          >
            <Icon name="download" size={14} />
          </button>
        </div>
      ))}
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
