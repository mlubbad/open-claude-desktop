import { type KeyboardEvent, useEffect, useMemo, useRef, useState } from "react";

import type { SkillSummary } from "../api/client";
import { type Attachment, clampContent, withAttachments } from "../state/attachments";
import { applySlash, slashSuggestions } from "../state/slashCommands";

export function Composer({
  busy,
  onSend,
  onStop,
  skills = [],
  draftKey = "new",
  initialText = "",
  onTextChange,
}: {
  busy: boolean;
  onSend: (text: string) => void;
  onStop: () => void;
  skills?: SkillSummary[];
  draftKey?: string;
  initialText?: string;
  onTextChange?: (text: string) => void;
}) {
  const [text, setTextState] = useState(initialText);
  const [sel, setSel] = useState(0);
  const [attachments, setAttachments] = useState<Attachment[]>([]);
  const fileRef = useRef<HTMLInputElement>(null);
  const suggestions = useMemo(() => slashSuggestions(skills, text), [skills, text]);
  const open = suggestions.length > 0;
  const active = Math.min(sel, Math.max(0, suggestions.length - 1));
  const canSend = (text.trim().length > 0 || attachments.length > 0) && !busy;

  // Wrap setText so every change is mirrored to the per-conversation draft store.
  const setText = (t: string) => {
    setTextState(t);
    onTextChange?.(t);
  };

  // Load the saved draft when the conversation switches (keyed on draftKey only, so it
  // doesn't clobber in-progress typing).
  const initialRef = useRef(initialText);
  initialRef.current = initialText;
  useEffect(() => {
    setTextState(initialRef.current);
    setAttachments([]);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [draftKey]);

  function submit() {
    if (!canSend) return;
    onSend(withAttachments(text, attachments));
    setText("");
    setAttachments([]);
  }

  async function addFiles(files: FileList | null) {
    if (!files) return;
    const read = await Promise.all(
      Array.from(files).map(
        (f) =>
          new Promise<Attachment>((resolve) => {
            const r = new FileReader();
            r.onload = () => resolve({ name: f.name, content: clampContent(String(r.result ?? "")) });
            r.onerror = () => resolve({ name: f.name, content: "" });
            r.readAsText(f);
          }),
      ),
    );
    setAttachments((a) => [...a, ...read.filter((x) => x.content)]);
  }

  function accept(skill: SkillSummary) {
    setText(applySlash(skill));
    setSel(0);
  }

  function onKey(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (open) {
      if (e.key === "ArrowDown") {
        e.preventDefault();
        setSel((s) => Math.min(s + 1, suggestions.length - 1));
        return;
      }
      if (e.key === "ArrowUp") {
        e.preventDefault();
        setSel((s) => Math.max(s - 1, 0));
        return;
      }
      if (e.key === "Tab" || (e.key === "Enter" && !e.shiftKey)) {
        e.preventDefault();
        accept(suggestions[active]);
        return;
      }
      if (e.key === "Escape") {
        e.preventDefault();
        setText(""); // clear the in-progress slash to dismiss the menu
        return;
      }
    }
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      submit();
    }
  }

  return (
    <div className="composer">
      {attachments.length > 0 && (
        <div className="attach-row">
          {attachments.map((a, i) => (
            <span key={i} className="attach-chip" title={a.name}>
              📄 {a.name}
              <button
                className="attach-del"
                title="Remove"
                onClick={() => setAttachments((prev) => prev.filter((_, j) => j !== i))}
              >
                ✕
              </button>
            </span>
          ))}
        </div>
      )}
      <input
        ref={fileRef}
        type="file"
        multiple
        accept=".txt,.md,.csv,.json,.py,.ts,.tsx,.js,.jsx,.html,.css,.yaml,.yml,.sql,.sh,.log,text/*"
        style={{ display: "none" }}
        onChange={(e) => {
          void addFiles(e.target.files);
          e.target.value = "";
        }}
      />
      {open && (
        <ul className="slash-menu">
          {suggestions.map((s, i) => (
            <li
              key={s.name}
              className={i === active ? "active" : ""}
              onMouseEnter={() => setSel(i)}
              onClick={() => accept(s)}
            >
              <span className="slash-name">/{s.name}</span>
              {s.description && <span className="slash-desc">{s.description}</span>}
            </li>
          ))}
        </ul>
      )}
      <button
        className="attach"
        title="Attach a text file"
        disabled={busy}
        onClick={() => fileRef.current?.click()}
      >
        📎
      </button>
      <textarea
        value={text}
        onChange={(e) => {
          setText(e.target.value);
          setSel(0);
        }}
        onKeyDown={onKey}
        placeholder="Message Open Claude Desktop…  (type / for skills)"
        rows={1}
      />
      {busy ? (
        <button className="stop" onClick={onStop} title="Stop">
          ■
        </button>
      ) : (
        <button className="send" onClick={submit} disabled={!canSend} title="Send">
          ↑
        </button>
      )}
    </div>
  );
}
