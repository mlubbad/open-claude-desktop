import { type KeyboardEvent, useEffect, useMemo, useRef, useState } from "react";

import type { SkillSummary } from "../api/client";
import { type Attachment, clampContent, withAttachments } from "../state/attachments";
import { applySlash, slashSuggestions } from "../state/slashCommands";
import { Icon } from "./Icon";

export const EFFORT_LEVELS = ["Low", "Medium", "High", "Max"] as const;

// Entries for the composer's tools popover (connectors / plugins / skills), each a
// jump into the matching settings page.
export interface ToolsMenuInfo {
  connectors: number;
  plugins: number;
  openConnectors: () => void;
  openPlugins: () => void;
  openSkills: () => void;
}

// The message composer card: textarea on top, a control row underneath — attach and
// tools on the left, model + effort + send on the right (mirroring the desktop
// pattern). Used both pinned at the bottom of a conversation and centered in the
// empty-state hero.
export function Composer({
  busy,
  onSend,
  onStop,
  skills = [],
  draftKey = "new",
  initialText = "",
  onTextChange,
  placeholder = "Write a message…",
  modelLabel,
  onModelClick,
  effort,
  onEffort,
  tools,
}: {
  busy: boolean;
  onSend: (text: string) => void;
  onStop: () => void;
  skills?: SkillSummary[];
  draftKey?: string;
  initialText?: string;
  onTextChange?: (text: string) => void;
  placeholder?: string;
  modelLabel?: string;
  onModelClick?: () => void;
  effort?: string;
  onEffort?: (e: string) => void;
  tools?: ToolsMenuInfo;
}) {
  const [text, setTextState] = useState(initialText);
  const [sel, setSel] = useState(0);
  const [attachments, setAttachments] = useState<Attachment[]>([]);
  const [toolsOpen, setToolsOpen] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);
  const toolsRef = useRef<HTMLDivElement>(null);
  const suggestions = useMemo(() => slashSuggestions(skills, text), [skills, text]);
  // Escape hides the menu without erasing the draft; typing re-arms it.
  const [dismissed, setDismissed] = useState(false);
  const open = suggestions.length > 0 && !dismissed;
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

  // Dismiss the tools popover on outside click or Escape. The Escape listener runs
  // in the capture phase and swallows the event so the global handler (which can
  // stop a running generation) never fires for a mere popover dismissal.
  useEffect(() => {
    if (!toolsOpen) return;
    function onDoc(e: MouseEvent) {
      if (!toolsRef.current?.contains(e.target as Node)) setToolsOpen(false);
    }
    // (globalThis.KeyboardEvent: the DOM event type — `KeyboardEvent` alone would
    // resolve to React's synthetic type imported above.)
    function onKey(e: globalThis.KeyboardEvent) {
      if (e.key === "Escape") {
        e.stopPropagation();
        e.preventDefault();
        setToolsOpen(false);
      }
    }
    document.addEventListener("mousedown", onDoc);
    document.addEventListener("keydown", onKey, true);
    return () => {
      document.removeEventListener("mousedown", onDoc);
      document.removeEventListener("keydown", onKey, true);
    };
  }, [toolsOpen]);

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
        e.stopPropagation(); // dismissing the menu must not reach the global Escape handler
        setDismissed(true); // hide the menu; keep the draft
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
              {a.name}
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
        <ul className="slash-menu" id="slash-listbox" role="listbox" aria-label="Skills">
          {suggestions.map((s, i) => (
            <li
              key={s.name}
              id={`slash-opt-${i}`}
              role="option"
              aria-selected={i === active}
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
      <textarea
        value={text}
        onChange={(e) => {
          setText(e.target.value);
          setSel(0);
          setDismissed(false);
        }}
        onKeyDown={onKey}
        placeholder={placeholder}
        rows={1}
        role="combobox"
        aria-expanded={open}
        aria-controls={open ? "slash-listbox" : undefined}
        aria-activedescendant={open ? `slash-opt-${active}` : undefined}
      />
      <div className="composer-row">
        <button
          className="composer-ghost attach"
          title="Attach a text file"
          aria-label="Attach a text file"
          disabled={busy}
          onClick={() => fileRef.current?.click()}
        >
          <Icon name="plus" />
        </button>
        {tools && (
          <div className="tools-anchor" ref={toolsRef}>
            <button
              className={`composer-ghost ${toolsOpen ? "active" : ""}`}
              title="Tools — connectors, plugins, skills"
              aria-label="Tools"
              aria-expanded={toolsOpen}
              onClick={() => setToolsOpen((o) => !o)}
            >
              <Icon name="sliders" />
            </button>
            {toolsOpen && (
              <div className="tools-menu" role="menu" aria-label="Tools">
                <button role="menuitem" onClick={() => { setToolsOpen(false); tools.openConnectors(); }}>
                  Connectors
                  {tools.connectors > 0 && <span className="tools-count">{tools.connectors} on</span>}
                </button>
                <button role="menuitem" onClick={() => { setToolsOpen(false); tools.openPlugins(); }}>
                  Plugins
                  {tools.plugins > 0 && <span className="tools-count">{tools.plugins} on</span>}
                </button>
                <button role="menuitem" onClick={() => { setToolsOpen(false); tools.openSkills(); }}>
                  Skills
                  <span className="tools-count">type /</span>
                </button>
              </div>
            )}
          </div>
        )}
        <span className="composer-spacer" />
        {modelLabel && (
          <button className="composer-pill model" title="Change model" onClick={onModelClick}>
            <span className="model-dot" aria-hidden="true" />
            {modelLabel}
            <span className="pill-caret" aria-hidden="true"><Icon name="chev-down" size={11} /></span>
          </button>
        )}
        {effort && onEffort && (
          <label className="composer-pill effort" title="Extended thinking effort">
            <select value={effort} onChange={(e) => onEffort(e.target.value)} aria-label="Effort">
              {EFFORT_LEVELS.map((l) => (
                <option key={l} value={l}>
                  {l}
                </option>
              ))}
            </select>
          </label>
        )}
        {busy ? (
          <button className="composer-send stop" onClick={onStop} title="Stop">
            ■
          </button>
        ) : (
          <button className="composer-send" onClick={submit} disabled={!canSend} title="Send">
            ↑
          </button>
        )}
      </div>
    </div>
  );
}
