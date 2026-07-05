import { useEffect, useRef, useState } from "react";

import { Icon } from "./Icon";

// The conversation-title breadcrumb dropdown: rename / export / delete for the open
// chat, anchored to the title in the top bar (the desktop title-caret pattern).
export function ChatMenu({
  title,
  onRename,
  onExport,
  onDelete,
}: {
  title: string;
  onRename: (title: string) => void;
  onExport: () => void;
  onDelete: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState<string | null>(null);
  const ref = useRef<HTMLDivElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);

  // Menu keyboard pattern: focus lands on the first item when the menu opens, and
  // the arrow keys cycle through the items.
  useEffect(() => {
    if (open && draft === null) {
      menuRef.current?.querySelector<HTMLButtonElement>('[role="menuitem"]')?.focus();
    }
  }, [open, draft]);

  function onMenuKey(e: React.KeyboardEvent) {
    if (e.key !== "ArrowDown" && e.key !== "ArrowUp") return;
    e.preventDefault();
    const items = Array.from(menuRef.current?.querySelectorAll<HTMLButtonElement>('[role="menuitem"]') ?? []);
    if (!items.length) return;
    const idx = items.indexOf(document.activeElement as HTMLButtonElement);
    const next = e.key === "ArrowDown" ? (idx + 1) % items.length : (idx - 1 + items.length) % items.length;
    items[next].focus();
  }

  useEffect(() => {
    if (!open) return;
    function onDoc(e: MouseEvent) {
      if (!ref.current?.contains(e.target as Node)) {
        setOpen(false);
        setDraft(null);
      }
    }
    // Capture-phase Escape: dismiss the menu and swallow the event so the global
    // Escape handler (which can stop a running generation) never sees it.
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") {
        e.stopPropagation();
        e.preventDefault();
        setOpen(false);
        setDraft(null);
      }
    }
    document.addEventListener("mousedown", onDoc);
    document.addEventListener("keydown", onKey, true);
    return () => {
      document.removeEventListener("mousedown", onDoc);
      document.removeEventListener("keydown", onKey, true);
    };
  }, [open]);

  function commit() {
    const t = (draft ?? "").trim();
    if (t && t !== title) onRename(t);
    setDraft(null);
    setOpen(false);
  }

  return (
    <div className="chat-menu-anchor" ref={ref}>
      <button
        className="crumb-title"
        title={title}
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
      >
        <span className="crumb-title-text">{title}</span>
        <span className="crumb-caret" aria-hidden="true">
          <Icon name="chev-down" size={12} />
        </span>
      </button>
      {open && (
        // While renaming, the popover holds a text input, not menu items — drop the
        // menu role so the ARIA structure stays truthful.
        <div
          ref={menuRef}
          className="chat-menu"
          role={draft === null ? "menu" : undefined}
          aria-label="Conversation actions"
          onKeyDown={onMenuKey}
        >
          {draft === null ? (
            <>
              <button role="menuitem" onClick={() => setDraft(title)}>
                <Icon name="pencil" size={13} /> Rename
              </button>
              <button role="menuitem" onClick={() => { setOpen(false); onExport(); }}>
                <Icon name="download" size={13} /> Export as Markdown
              </button>
              <button role="menuitem" className="danger" onClick={() => { setOpen(false); onDelete(); }}>
                <Icon name="x" size={13} /> Delete chat
              </button>
            </>
          ) : (
            <input
              className="chat-menu-rename"
              autoFocus
              aria-label="Rename conversation"
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") commit();
                // Escape is handled by the document-level capture listener above.
              }}
              onBlur={commit}
            />
          )}
        </div>
      )}
    </div>
  );
}
