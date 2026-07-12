import { type KeyboardEvent, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";

import { mcp, type SkillSummary } from "../api/client";
import {
  admitImages,
  type Attachment,
  clampContent,
  type ImageAttachment,
  isImageFile,
  withAttachments,
} from "../state/attachments";
import { applySlash, slashSuggestions } from "../state/slashCommands";
import type { McpSlashPrompt } from "../state/useMcpPrompts";

// A `/` suggestion is either an Agent Skill or an MCP prompt (P1-2).
type SlashItem = SkillSummary | McpSlashPrompt;
import { Icon } from "./Icon";
import { MicPicker, type VoiceInfo } from "./MicPicker";
import { ModelPicker } from "./ModelPicker";

// Backwards-compatible effort list (kept for existing imports/tests).
export const EFFORT_LEVELS = ["Low", "Medium", "High", "Extra", "Max"] as const;

// A project the current conversation can be filed under (null id slot = General).
export interface ProjectRef {
  id: string;
  name: string;
}

// A connector row for the composer's Connectors flyout.
export interface ConnectorRef {
  id: string;
  name: string;
  status: string; // "connected" | "error" | "unauthorized" | …
}

// An installed-plugin row for the composer's Plugins flyout.
export interface PluginRef {
  name: string;
  description?: string;
}

// The full `+` Add menu (contract §2): file/project/GitHub adds, the Skills/
// Connectors/Plugins jumps, and the Research / Web-search request toggles.
export interface AddMenuInfo {
  // "Add to project" flyout: the projects to file THIS conversation under, the one
  // it currently lives in (null = General), and the pick / create handlers.
  projects: ProjectRef[];
  activeProjectId: string | null;
  onPickProject: (id: string | null) => void;
  onCreateProject: () => void;
  onAddFromGitHub: () => void;
  // Skills / Connectors / Plugins each open as a flyout (live list + toggle where it
  // applies) instead of jumping straight to Settings; "Manage…" still does that.
  openSkills: () => void;
  connectors: ConnectorRef[];
  enabledConnectors: string[];
  onToggleConnector: (id: string) => void;
  openConnectors: () => void;
  pluginsList: PluginRef[];
  enabledPlugins: string[];
  onTogglePlugin: (name: string) => void;
  openPlugins: () => void;
  openMarketplace: () => void;
  research: boolean;
  onResearch: (on: boolean) => void;
  webSearch: boolean;
  onWebSearch: (on: boolean) => void;
  codeExec: boolean;
  onCodeExec: (on: boolean) => void;
  // Response style (P0-6): per-conversation, like model + effort.
  style: string;
  onStyle: (style: string) => void;
}

// The selectable response styles (labels for the flyout).
export const STYLE_OPTIONS: { value: string; label: string }[] = [
  { value: "normal", label: "Normal" },
  { value: "concise", label: "Concise" },
  { value: "explanatory", label: "Explanatory" },
  { value: "formal", label: "Formal" },
];

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
  mcpPrompts = [],
  draftKey = "new",
  initialText = "",
  onTextChange,
  placeholder = "Write a message…",
  addMenu,
  modelControl,
  voice,
  modeToggle,
}: {
  busy: boolean;
  onSend: (text: string, images?: string[]) => void;
  onStop: () => void;
  skills?: SkillSummary[];
  mcpPrompts?: McpSlashPrompt[];
  draftKey?: string;
  initialText?: string;
  onTextChange?: (text: string) => void;
  placeholder?: string;
  addMenu?: AddMenuInfo;
  modelControl?: ModelControlInfo;
  voice?: VoiceInfo;
  // Chat | Cowork mode switch (reference parity): flips the whole surface between
  // an interactive chat and delegating an autonomous background task.
  modeToggle?: { mode: "chat" | "cowork"; onMode: (m: "chat" | "cowork") => void };
}) {
  const [text, setTextState] = useState(initialText);
  const [sel, setSel] = useState(0);
  const [attachments, setAttachments] = useState<Attachment[]>([]);
  const [images, setImages] = useState<ImageAttachment[]>([]);
  // Drag-and-drop: depth counter (enter/leave fire per child) drives the drop overlay.
  const [dragDepth, setDragDepth] = useState(0);
  const [addOpen, setAddOpen] = useState(false);
  // Which Add-menu flyout is open (Add to project / Skills / Connectors / Plugins) —
  // only one at a time, hover- or click-driven, mirroring the Recents ⋮ submenu.
  const [subOpen, setSubOpen] = useState<"project" | "skills" | "connectors" | "plugins" | "style" | null>(null);
  const [modelOpen, setModelOpen] = useState(false);
  const [micOpen, setMicOpen] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);
  const addRef = useRef<HTMLDivElement>(null);
  const taRef = useRef<HTMLTextAreaElement>(null);

  // Auto-grow the textarea to fit its content (up to the CSS max-height, then it
  // scrolls) so a long prompt is fully visible instead of clipped to one line —
  // Claude-Desktop behaviour. Runs on every value change (typing, paste, draft load).
  // useLayoutEffect measures+sets height BEFORE paint, so loading a multi-line draft
  // (or switching conversations) never flashes at one-row height for a frame first.
  useLayoutEffect(() => {
    const ta = taRef.current;
    if (!ta) return;
    ta.style.height = "auto";
    ta.style.height = `${ta.scrollHeight}px`;
  }, [text]);
  const addMenuRef = useRef<HTMLDivElement>(null);
  const suggestions = useMemo(
    () => slashSuggestions<SlashItem>([...skills, ...mcpPrompts], text),
    [skills, mcpPrompts, text],
  );
  // Escape hides the menu without erasing the draft; typing re-arms it.
  const [dismissed, setDismissed] = useState(false);
  const open = suggestions.length > 0 && !dismissed;
  const active = Math.min(sel, Math.max(0, suggestions.length - 1));
  const canSend = (text.trim().length > 0 || attachments.length > 0 || images.length > 0) && !busy;

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
    setImages([]);
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
    if (!addOpen) {
      setSubOpen(null); // collapse any open flyout when the menu closes
      return;
    }
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
    onSend(withAttachments(text, attachments), images.map((i) => i.dataUrl));
    setText("");
    setAttachments([]);
    setImages([]);
  }

  // Images become data-URI vision input (thumbnail chips); everything else is read
  // as text and inlined into the message. Used by the picker, drag-drop, and paste.
  async function addFiles(files: FileList | null) {
    if (!files) return;
    const all = Array.from(files);
    const imgs = admitImages(images.length, all.filter(isImageFile));
    const texts = all.filter((f) => !isImageFile(f));

    const readImgs = await Promise.all(
      imgs.map(
        (f) =>
          new Promise<ImageAttachment>((resolve) => {
            const r = new FileReader();
            r.onload = () => resolve({ name: f.name, dataUrl: String(r.result ?? "") });
            r.onerror = () => resolve({ name: f.name, dataUrl: "" });
            r.readAsDataURL(f);
          }),
      ),
    );
    setImages((a) => [...a, ...readImgs.filter((x) => x.dataUrl.startsWith("data:image/"))]);

    const readTexts = await Promise.all(
      texts.map(
        (f) =>
          new Promise<Attachment>((resolve) => {
            const r = new FileReader();
            r.onload = () => resolve({ name: f.name, content: clampContent(String(r.result ?? "")) });
            r.onerror = () => resolve({ name: f.name, content: "" });
            r.readAsText(f);
          }),
      ),
    );
    setAttachments((a) => [...a, ...readTexts.filter((x) => x.content)]);
  }

  function accept(item: SlashItem) {
    if ("sid" in item) {
      // MCP prompt (P1-2): render it server-side and insert the resulting text —
      // the user reviews/edits before sending.
      void mcp
        .getPrompt(item.sid, item.prompt)
        .then((r) => setText(r.messages.map((m) => m.content).join("\n\n")))
        .catch(() => setText(""));
      setSel(0);
      return;
    }
    setText(applySlash(item));
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
    <div
      className={`composer ${dragDepth > 0 ? "dragging" : ""}`}
      onDragEnter={(e) => {
        if (e.dataTransfer.types.includes("Files")) {
          e.preventDefault();
          setDragDepth((d) => d + 1);
        }
      }}
      onDragOver={(e) => {
        if (e.dataTransfer.types.includes("Files")) e.preventDefault();
      }}
      onDragLeave={() => setDragDepth((d) => Math.max(0, d - 1))}
      onDrop={(e) => {
        e.preventDefault();
        setDragDepth(0);
        if (!busy) void addFiles(e.dataTransfer.files);
      }}
    >
      {dragDepth > 0 && (
        <div className="composer-drop-overlay" aria-hidden="true">
          Drop files to attach
        </div>
      )}
      {(attachments.length > 0 || images.length > 0) && (
        <div className="attach-row">
          {images.map((img, i) => (
            <span key={`img-${i}`} className="attach-chip attach-img" title={img.name}>
              <img src={img.dataUrl} alt={img.name} className="attach-thumb" />
              <button
                className="attach-del"
                title="Remove image"
                aria-label={`Remove image ${img.name}`}
                onClick={() => setImages((prev) => prev.filter((_, j) => j !== i))}
              >
                ✕
              </button>
            </span>
          ))}
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
        accept="image/*,.png,.jpg,.jpeg,.gif,.webp,.txt,.md,.csv,.json,.py,.ts,.tsx,.js,.jsx,.html,.css,.yaml,.yml,.sql,.sh,.log,text/*"
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
        ref={taRef}
        value={text}
        onChange={(e) => {
          setText(e.target.value);
          setSel(0);
          setDismissed(false);
        }}
        onPaste={(e) => {
          // Clipboard images (screenshots!) attach as vision input; text pastes fall
          // through to the normal text path untouched.
          const files = Array.from(e.clipboardData?.files ?? []).filter(isImageFile);
          if (files.length > 0) {
            e.preventDefault();
            const dt = new DataTransfer();
            for (const f of files) dt.items.add(f);
            void addFiles(dt.files);
          }
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
              <div
                className="add-submenu-anchor"
                onMouseEnter={() => setSubOpen("project")}
                onMouseLeave={() => setSubOpen((s) => (s === "project" ? null : s))}
              >
                <button
                  role="menuitem"
                  aria-haspopup="menu"
                  aria-expanded={subOpen === "project"}
                  onClick={() => setSubOpen((s) => (s === "project" ? null : "project"))}
                >
                  <span className="add-ic"><Icon name="folder" size={15} /></span>
                  Add to project
                  <span className="add-chev" aria-hidden="true"><Icon name="chev-right" size={13} /></span>
                </button>
                {subOpen === "project" && (
                  <div className="add-submenu" role="menu" aria-label="Add to project">
                    <button
                      role="menuitemradio"
                      aria-checked={addMenu.activeProjectId === null}
                      onClick={() => { setAddOpen(false); addMenu.onPickProject(null); }}
                    >
                      General
                      {addMenu.activeProjectId === null && (
                        <span className="add-check" aria-hidden="true"><Icon name="check" size={13} /></span>
                      )}
                    </button>
                    {addMenu.projects.map((p) => (
                      <button
                        key={p.id}
                        role="menuitemradio"
                        aria-checked={addMenu.activeProjectId === p.id}
                        onClick={() => { setAddOpen(false); addMenu.onPickProject(p.id); }}
                      >
                        <span className="add-submenu-name">{p.name}</span>
                        {addMenu.activeProjectId === p.id && (
                          <span className="add-check" aria-hidden="true"><Icon name="check" size={13} /></span>
                        )}
                      </button>
                    ))}
                    <div className="add-divider" />
                    <button
                      role="menuitem"
                      onClick={() => { setAddOpen(false); addMenu.onCreateProject(); }}
                    >
                      <span className="add-ic"><Icon name="plus" size={14} /></span>
                      New project
                    </button>
                  </div>
                )}
              </div>
              <button role="menuitem" onClick={() => { setAddOpen(false); addMenu.onAddFromGitHub(); }}>
                <span className="add-ic"><Icon name="book" size={15} /></span>
                Add from GitHub
              </button>
              <div className="add-divider" />

              <div
                className="add-submenu-anchor"
                onMouseEnter={() => setSubOpen("skills")}
                onMouseLeave={() => setSubOpen((s) => (s === "skills" ? null : s))}
              >
                <button
                  role="menuitem"
                  aria-haspopup="menu"
                  aria-expanded={subOpen === "skills"}
                  onClick={() => setSubOpen((s) => (s === "skills" ? null : "skills"))}
                >
                  <span className="add-ic"><Icon name="bulb" size={15} /></span>
                  Skills
                  <span className="add-chev" aria-hidden="true"><Icon name="chev-right" size={13} /></span>
                </button>
                {subOpen === "skills" && (
                  <div className="add-submenu" role="menu" aria-label="Skills">
                    {skills.map((s) => (
                      <button
                        key={s.name}
                        role="menuitem"
                        title={s.description}
                        onClick={() => { setAddOpen(false); accept(s); }}
                      >
                        <span className="add-submenu-name">/{s.name}</span>
                      </button>
                    ))}
                    {skills.length === 0 && <span className="add-submenu-empty">No skills yet</span>}
                    <div className="add-divider" />
                    <button role="menuitem" onClick={() => { setAddOpen(false); addMenu.openSkills(); }}>
                      Manage &amp; import skills
                    </button>
                  </div>
                )}
              </div>

              <div
                className="add-submenu-anchor"
                onMouseEnter={() => setSubOpen("connectors")}
                onMouseLeave={() => setSubOpen((s) => (s === "connectors" ? null : s))}
              >
                <button
                  role="menuitem"
                  aria-haspopup="menu"
                  aria-expanded={subOpen === "connectors"}
                  onClick={() => setSubOpen((s) => (s === "connectors" ? null : "connectors"))}
                >
                  <span className="add-ic"><Icon name="sliders" size={15} /></span>
                  Connectors
                  {addMenu.connectors.some((c) => c.status === "error") && (
                    <span className="add-warn" aria-hidden="true">
                      {addMenu.connectors.filter((c) => c.status === "error").length}
                    </span>
                  )}
                  <span className="add-chev" aria-hidden="true"><Icon name="chev-right" size={13} /></span>
                </button>
                {subOpen === "connectors" && (
                  <div className="add-submenu" role="menu" aria-label="Connectors">
                    {addMenu.connectors.map((c) => (
                      <button
                        key={c.id}
                        role="menuitemcheckbox"
                        aria-checked={addMenu.enabledConnectors.includes(c.id)}
                        disabled={c.status !== "connected"}
                        onClick={() => addMenu.onToggleConnector(c.id)}
                      >
                        <span className="add-submenu-name">{c.name}</span>
                        {c.status !== "connected" && <span className="add-submenu-sub">{c.status}</span>}
                        {addMenu.enabledConnectors.includes(c.id) && (
                          <span className="add-check" aria-hidden="true"><Icon name="check" size={13} /></span>
                        )}
                      </button>
                    ))}
                    {addMenu.connectors.length === 0 && <span className="add-submenu-empty">No connectors yet</span>}
                    <div className="add-divider" />
                    <button role="menuitem" onClick={() => { setAddOpen(false); addMenu.openConnectors(); }}>
                      Manage connectors
                    </button>
                  </div>
                )}
              </div>

              <div
                className="add-submenu-anchor"
                onMouseEnter={() => setSubOpen("plugins")}
                onMouseLeave={() => setSubOpen((s) => (s === "plugins" ? null : s))}
              >
                <button
                  role="menuitem"
                  aria-haspopup="menu"
                  aria-expanded={subOpen === "plugins"}
                  onClick={() => setSubOpen((s) => (s === "plugins" ? null : "plugins"))}
                >
                  <span className="add-ic"><Icon name="panel" size={15} /></span>
                  Plugins
                  <span className="add-chev" aria-hidden="true"><Icon name="chev-right" size={13} /></span>
                </button>
                {subOpen === "plugins" && (
                  <div className="add-submenu" role="menu" aria-label="Plugins">
                    {addMenu.pluginsList.map((pl) => (
                      <button
                        key={pl.name}
                        role="menuitemcheckbox"
                        aria-checked={addMenu.enabledPlugins.includes(pl.name)}
                        title={pl.description}
                        onClick={() => addMenu.onTogglePlugin(pl.name)}
                      >
                        <span className="add-submenu-name">{pl.name}</span>
                        {addMenu.enabledPlugins.includes(pl.name) && (
                          <span className="add-check" aria-hidden="true"><Icon name="check" size={13} /></span>
                        )}
                      </button>
                    ))}
                    {addMenu.pluginsList.length === 0 && <span className="add-submenu-empty">No plugins yet</span>}
                    <div className="add-divider" />
                    <button role="menuitem" onClick={() => { setAddOpen(false); addMenu.openPlugins(); }}>
                      Manage plugins
                    </button>
                    <button role="menuitem" onClick={() => { setAddOpen(false); addMenu.openMarketplace(); }}>
                      Browse marketplace
                    </button>
                  </div>
                )}
              </div>
              <div className="add-divider" />
              <div
                className="add-submenu-anchor"
                onMouseEnter={() => setSubOpen("style")}
                onMouseLeave={() => setSubOpen((s) => (s === "style" ? null : s))}
              >
                <button
                  role="menuitem"
                  aria-haspopup="menu"
                  aria-expanded={subOpen === "style"}
                  onClick={() => setSubOpen((s) => (s === "style" ? null : "style"))}
                >
                  <span className="add-ic"><Icon name="pencil" size={15} /></span>
                  Response style
                  <span className="add-submenu-sub">
                    {STYLE_OPTIONS.find((o) => o.value === addMenu.style)?.label ?? "Normal"}
                  </span>
                  <span className="add-chev" aria-hidden="true"><Icon name="chev-right" size={13} /></span>
                </button>
                {subOpen === "style" && (
                  <div className="add-submenu" role="menu" aria-label="Response style">
                    {STYLE_OPTIONS.map((o) => (
                      <button
                        key={o.value}
                        role="menuitemradio"
                        aria-checked={addMenu.style === o.value}
                        onClick={() => { setAddOpen(false); addMenu.onStyle(o.value); }}
                      >
                        <span className="add-submenu-name">{o.label}</span>
                        {addMenu.style === o.value && (
                          <span className="add-check" aria-hidden="true"><Icon name="check" size={13} /></span>
                        )}
                      </button>
                    ))}
                  </div>
                )}
              </div>
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
              <button role="menuitemcheckbox" aria-checked={addMenu.codeExec}
                      onClick={() => addMenu.onCodeExec(!addMenu.codeExec)}
                      title="Let the agent run Python and produce files (each run asks for approval)">
                <span className="add-ic"><Icon name="code" size={15} /></span>
                Code execution
                {addMenu.codeExec && <span className="add-check" aria-hidden="true"><Icon name="check" size={14} /></span>}
              </button>
            </div>
          )}
        </div>
        {modeToggle && (
          <div className="composer-mode" role="group" aria-label="Chat or Cowork">
            <button
              className={`composer-mode-btn ${modeToggle.mode === "chat" ? "active" : ""}`}
              aria-pressed={modeToggle.mode === "chat"}
              onClick={() => modeToggle.onMode("chat")}
            >
              Chat
            </button>
            <button
              className={`composer-mode-btn ${modeToggle.mode === "cowork" ? "active" : ""}`}
              aria-pressed={modeToggle.mode === "cowork"}
              title="Give Claude a task (or a few) to run autonomously"
              onClick={() => modeToggle.onMode("cowork")}
            >
              Cowork
            </button>
          </div>
        )}
        {/* Context chips (Claude-Desktop style): keep the user aware that this chat is
            grounded on a project / has Research on, with an ✕ to drop each. */}
        {addMenu?.activeProjectId && (
          <span
            className="ctx-chip"
            title={`Project: ${addMenu.projects.find((p) => p.id === addMenu.activeProjectId)?.name ?? "project"}`}
          >
            <Icon name="folder" size={14} />
            <button
              className="ctx-chip-x"
              title="Remove chat from project"
              aria-label="Remove chat from project"
              onClick={() => addMenu.onPickProject(null)}
            >
              <Icon name="x" size={11} />
            </button>
          </span>
        )}
        {addMenu?.research && (
          <span className="ctx-chip" title="Research mode">
            <Icon name="chart" size={14} />
            <button
              className="ctx-chip-x"
              title="Turn off Research"
              aria-label="Turn off Research"
              onClick={() => addMenu.onResearch(false)}
            >
              <Icon name="x" size={11} />
            </button>
          </span>
        )}
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
