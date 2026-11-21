import { useEffect, useRef, useState } from "react";

import type { Project } from "../api/client";
import { useMenuFit } from "../state/useMenuFit";
import { Icon } from "./Icon";

// The recents-row ⋮ overflow menu (contract §7.3): Pin/Unpin (P), Rename (R), a
// project submenu (Add to / Change / Remove), and Delete (D) in the error colour.
// Shortcut letters are shown right-aligned. Anchored to the row's ⋮ button.
export function ConvMenu({
  pinned,
  inProject,
  projects,
  currentProjectId,
  onPin,
  onRename,
  onMove,
  onDelete,
  onClose,
}: {
  pinned: boolean;
  inProject: boolean;
  projects: Project[];
  currentProjectId: string;
  onPin: () => void;
  onRename: () => void;
  onMove: (dstProjectId: string) => void;
  onDelete: () => void;
  onClose: () => void;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const subRef = useRef<HTMLDivElement>(null);
  const [submenu, setSubmenu] = useState(false);
  useMenuFit(ref, true); // main menu is only mounted while open
  useMenuFit(subRef, submenu); // the "Change project" flyout — flip in from either edge

  useEffect(() => {
    function onDoc(e: MouseEvent) {
      if (!ref.current?.contains(e.target as Node)) onClose();
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") {
        e.stopPropagation();
        e.preventDefault();
        onClose();
      }
    }
    document.addEventListener("mousedown", onDoc);
    document.addEventListener("keydown", onKey, true);
    return () => {
      document.removeEventListener("mousedown", onDoc);
      document.removeEventListener("keydown", onKey, true);
    };
  }, [onClose]);

  // General + real projects, minus the one this chat already lives in.
  const targets = [{ id: "general", name: "General" }, ...projects].filter((p) => p.id !== currentProjectId);

  return (
    <div className="conv-menu" role="menu" aria-label="Conversation actions" ref={ref}>
      <button role="menuitem" onClick={() => { onClose(); onPin(); }}>
        <span className="cm-ic"><Icon name={pinned ? "pin-filled" : "pin"} size={13} /></span>
        {pinned ? "Unpin" : "Pin"}
        <span className="cm-key">P</span>
      </button>
      <button role="menuitem" onClick={() => { onClose(); onRename(); }}>
        <span className="cm-ic"><Icon name="pencil" size={13} /></span>
        Rename
        <span className="cm-key">R</span>
      </button>
      <div className="conv-submenu-anchor"
           onMouseEnter={() => setSubmenu(true)} onMouseLeave={() => setSubmenu(false)}>
        <button role="menuitem" aria-haspopup="menu" aria-expanded={submenu}>
          <span className="cm-ic"><Icon name="folder" size={13} /></span>
          {inProject ? "Change project" : "Add to project"}
          <span className="cm-chev" aria-hidden="true"><Icon name="chev-right" size={12} /></span>
        </button>
        {submenu && (
          <div className="conv-submenu" role="menu" aria-label="Move to project" ref={subRef}>
            {targets.map((t) => (
              <button key={t.id} role="menuitem" onClick={() => { onClose(); onMove(t.id); }}>
                {t.name}
              </button>
            ))}
            {targets.length === 0 && <span className="conv-submenu-empty">No other projects</span>}
          </div>
        )}
      </div>
      <div className="conv-menu-divider" />
      <button role="menuitem" className="cm-danger" onClick={() => { onClose(); onDelete(); }}>
        <span className="cm-ic"><Icon name="x" size={13} /></span>
        Delete
        <span className="cm-key">D</span>
      </button>
    </div>
  );
}
