import { type KeyboardEvent, useEffect, useMemo, useRef, useState } from "react";

import type { SkillSummary } from "../api/client";
import { type Attachment, clampContent, withAttachments } from "../state/attachments";
import { applySlash, slashSuggestions } from "../state/slashCommands";
import { Icon } from "./Icon";
import { MicPicker, type VoiceInfo } from "./MicPicker";
import { ModelPicker } from "./ModelPicker";

// Backwards-compatible effort list (kept for existing imports/tests).
export const EFFORT_LEVELS = ["Low", "Medium", "High", "Extra", "Max"] as const;

// The full `+` Add menu (contract §2): file/project/GitHub adds, the Skills/
// Connectors/Plugins jumps, and the Research / Web-search request toggles.
export interface AddMenuInfo {
  onAddToProject: () => void;
  onAddFromGitHub: () => void;
  openSkills: () => void;
  openConnectors: () => void;
  openPlugins: () => void;
  research: boolean;
  onResearch: (on: boolean) => void;
  webSearch: boolean;
  onWebSearch: (on: boolean) => void;
}

// The model + effort control (contract §3), rendered as a pill that opens the
// two-column picker. Selections apply instantly; the caller persists per conversation.
export interface ModelControlInfo {
  provider: string;
  model: string;
  effort: string;
  thinking: boolean;
  onSelectModel: (provider: string, model: string) => void;
  onSelectEffort: (e: string) => void;
  onToggleThinking: (on: boolean) => void;
  onMoreModels: () => void;
}

// The message composer card: textarea on top, a control row underneath — `+` add
// menu and tools on the left, model + effort + mic + send on the right (mirroring
// the reference). Used both pinned at the bottom of a conversation and centered in
// the empty-state hero.
export function Composer({
  busy,
  onSend,
  onStop,
  skills = [],
  draftKey = "new",
  initialText = "",
  onTextChange,
  placeholder = "Write a message…",
  addMenu,
  modelControl,
  voice,
}: {
  busy: boolean;
  onSend: (text: string) => void;
  onStop: () => void;
  skills?: SkillSummary[];
  draftKey?: string;
  initialText?: string;
  onTextChange?: (text: string) => void;
  placeholder?: string;
  addMenu?: AddMenuInfo;
  modelControl?: ModelControlInfo;
  voice?: VoiceInfo;
}) {
  const [text, setTextState] = useState(initialText);
  const [sel, setSel] = useState(0);
  const [attachments, setAttachments] = useState<Attachment[]>([]);
  const [addOpen, setAddOpen] = useState(false);
  const [modelOpen, setModelOpen] = useState(false);
  const [micOpen, setMicOpen] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);
  const addRef = useRef<HTMLDivElement>(null);
  const addMenuRef = useRef<HTMLDivElement>(null);
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

  // Ctrl/Cmd+U -> attach files (contract §2 shortcut hint).
  useEffect(() => {
    function onKey(e: globalThis.KeyboardEvent) {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "u") {
        e.preventDefault();
        fileRef.current?.click();
      }
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, []);

  // Dismiss the add menu on outside click / Escape (Escape swallowed so it doesn't
  // reach the global handler that stops generation).
  useEffect(() => {
    if (!addOpen) return;
    function onDoc(e: MouseEvent) {
      if (!addRef.current?.contains(e.target as Node)) setAddOpen(false);
    }
    function onKey(e: globalThis.KeyboardEvent) {
      if (e.key === "Escape") {
        e.stopPropagation();
        e.preventDefault();
        setAddOpen(false);
      }
    }
    document.addEventListener("mousedown", onDoc);
    document.addEventListener("keydown", onKey, true);
    addMenuRef.current?.querySelector<HTMLButtonElement>('[role="menuitem"]')?.focus();
    return () => {
      document.removeEventListener("mousedown", onDoc);
      document.removeEventListener("keydown", onKey, true);
    };
  }, [addOpen]);

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
        e.stopPropagation();
        setDismissed(true);
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
        dir="auto"
        role="combobox"
        aria-expanded={open}
        aria-controls={open ? "slash-listbox" : undefined}
        aria-activedescendant={open ? `slash-opt-${active}` : undefined}
      />
      <div className="composer-row">
        <div className="add-anchor" ref={addRef}>
          <button
            className={`composer-ghost ${addOpen ? "active" : ""}`}
            title="Add files, tools & more"
            aria-label="Add menu"
            aria-expanded={addOpen}
            disabled={busy}
            onClick={() => (addMenu ? setAddOpen((o) => !o) : fileRef.current?.click())}
          >
            <Icon name="plus" />
          </button>
          {addOpen && addMenu && (
            <div className="add-menu" role="menu" aria-label="Add" ref={addMenuRef}>
              <button role="menuitem" onClick={() => { setAddOpen(false); fileRef.current?.click(); }}>
                <span className="add-ic"><Icon name="file" size={15} /></span>
                Add files or photos
                <span className="add-shortcut">Ctrl+U</span>
              </button>
              <button role="menuitem" onClick={() => { setAddOpen(false); addMenu.onAddToProject(); }}>
                <span className="add-ic"><Icon name="folder" size={15} /></span>
                Add to project
                <span className="add-chev" aria-hidden="true"><Icon name="chev-right" size={13} /></span>
              </button>
              <button role="menuitem" onClick={() => { setAddOpen(false); addMenu.onAddFromGitHub(); }}>
                <span className="add-ic"><Icon name="book" size={15} /></span>
                Add from GitHub
              </button>
              <div className="add-divider" />
              <button role="menuitem" onClick={() => { setAddOpen(false); addMenu.openSkills(); }}>
                <span className="add-ic"><Icon name="bulb" size={15} /></span>
                Skills
                <span className="add-chev" aria-hidden="true"><Icon name="chev-right" size={13} /></span>
              </button>
              <button role="menuitem" onClick={() => { setAddOpen(false); addMenu.openConnectors(); }}>
                <span className="add-ic"><Icon name="sliders" size={15} /></span>
                Connectors
                <span className="add-chev" aria-hidden="true"><Icon name="chev-right" size={13} /></span>
              </button>
              <button role="menuitem" onClick={() => { setAddOpen(false); addMenu.openPlugins(); }}>
                <span className="add-ic"><Icon name="panel" size={15} /></span>
                Plugins
                <span className="add-chev" aria-hidden="true"><Icon name="chev-right" size={13} /></span>
              </button>
              <div className="add-divider" />
              <button role="menuitemcheckbox" aria-checked={addMenu.research}
                      onClick={() => addMenu.onResearch(!addMenu.research)}>
                <span className="add-ic"><Icon name="chart" size={15} /></span>
                Research
                {addMenu.research && <span className="add-check" aria-hidden="true"><Icon name="check" size={14} /></span>}
              </button>
              <button role="menuitemcheckbox" aria-checked={addMenu.webSearch}
                      onClick={() => addMenu.onWebSearch(!addMenu.webSearch)}>
                <span className="add-ic"><Icon name="book" size={15} /></span>
                Web search
                {addMenu.webSearch && <span className="add-check" aria-hidden="true"><Icon name="check" size={14} /></span>}
              </button>
            </div>
          )}
        </div>
        <span className="composer-spacer" />
        {modelControl && (
          <div className="model-anchor">
            <button
              className="composer-pill model"
              title="Model & effort"
              aria-haspopup="dialog"
              aria-expanded={modelOpen}
              onClick={() => setModelOpen((o) => !o)}
            >
              <span className="model-dot" aria-hidden="true" />
              <span className="model-name">{modelControl.model.split("/").pop()}</span>
              <span className="model-effort">{modelControl.effort}</span>
              <span className="pill-caret" aria-hidden="true"><Icon name="chev-down" size={11} /></span>
            </button>
            {modelOpen && (
              <ModelPicker
                provider={modelControl.provider}
                model={modelControl.model}
                effort={modelControl.effort}
                thinking={modelControl.thinking}
                onSelectModel={(p, m) => modelControl.onSelectModel(p, m)}
                onSelectEffort={modelControl.onSelectEffort}
                onToggleThinking={modelControl.onToggleThinking}
                onMoreModels={() => { setModelOpen(false); modelControl.onMoreModels(); }}
                onClose={() => setModelOpen(false)}
              />
            )}
          </div>
        )}
        {voice && (
          <div className="mic-anchor">
            <button
              className={`composer-ghost bare ${micOpen ? "active" : ""}`}
              title="Microphone"
              aria-label="Microphone"
              aria-expanded={micOpen}
              onClick={() => setMicOpen((o) => !o)}
            >
              <Icon name="mic" size={17} />
            </button>
            {micOpen && <MicPicker voice={voice} onClose={() => setMicOpen(false)} />}
          </div>
        )}
        {voice && (
          <button className="composer-ghost bare" title="Voice mode" aria-label="Voice mode"
                  onClick={voice.onVoiceMode}>
            <Icon name="waveform" size={17} />
          </button>
        )}
        {busy ? (
          <button className="composer-send stop" onClick={onStop} title="Stop" aria-label="Stop">
            <span className="send-stop-glyph" aria-hidden="true" />
          </button>
        ) : (
          <button className="composer-send" onClick={submit} disabled={!canSend} title="Send" aria-label="Send">
            <Icon name="arrow-up" size={17} />
          </button>
        )}
      </div>
    </div>
  );
}
