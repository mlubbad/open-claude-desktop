import { type ReactNode, useEffect, useRef, useState } from "react";

import type { Project, ProjectFile } from "../api/client";
import { Icon } from "./Icon";

// The project home (Claude Desktop parity): a breadcrumb, the project title, a project-
// scoped composer, and a right rail with Instructions / Memory / Context (knowledge
// files) cards. Starting a chat here scopes it to the project and picks up its context.
export function ProjectHome({
  project,
  instructions,
  memory,
  memoryUpdated,
  files,
  composer,
  onBack,
  onEditInstructions,
  onUploadFile,
  onAddText,
  onRemoveFile,
  onEditDetails,
  onTogglePin,
  onArchive,
  onDelete,
}: {
  project: Project;
  instructions: string;
  memory: string;
  memoryUpdated: string;
  files: ProjectFile[];
  composer: ReactNode;
  onBack: () => void;
  onEditInstructions: () => void;
  onUploadFile: (file: File) => void;
  onAddText: () => void;
  onRemoveFile: (name: string) => void;
  onEditDetails: () => void;
  onTogglePin: () => void;
  onArchive: () => void;
  onDelete: () => void;
}) {
  const [menuOpen, setMenuOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!menuOpen) return;
    function onDoc(e: MouseEvent) {
      if (!menuRef.current?.contains(e.target as Node)) setMenuOpen(false);
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") setMenuOpen(false);
    }
    document.addEventListener("mousedown", onDoc);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDoc);
      document.removeEventListener("keydown", onKey);
    };
  }, [menuOpen]);

  const instrPreview = instructions.replace(/^#.*$/m, "").trim() || instructions.trim();

  return (
    <div className="project-home">
      <div className="project-home-bar">
        <nav className="project-crumbs" aria-label="Breadcrumb">
          <button className="crumb-link" onClick={onBack}>Projects</button>
          <span className="crumb-sep">/</span>
          <span className="crumb-current">{project.name}</span>
        </nav>
      </div>

      <div className="project-home-body">
        <div className="project-home-main">
          <div className="project-home-title-row">
            <h1 className="project-home-title">{project.name}</h1>
            <div className="project-home-actions">
              <button
                className={`icon-btn ${project.pinned ? "active" : ""}`}
                title={project.pinned ? "Unpin project" : "Pin project"}
                aria-label={project.pinned ? "Unpin project" : "Pin project"}
                aria-pressed={project.pinned}
                onClick={onTogglePin}
              >
                <Icon name={project.pinned ? "pin-filled" : "pin"} size={16} />
              </button>
              <div className="project-home-menu" ref={menuRef}>
                <button className="icon-btn" aria-label="Project options" aria-expanded={menuOpen}
                        onClick={() => setMenuOpen((o) => !o)}>
                  <Icon name="dots" size={16} />
                </button>
                {menuOpen && (
                  <div className="card-menu" role="menu">
                    <button role="menuitem" onClick={() => { setMenuOpen(false); onEditDetails(); }}>
                      <Icon name="pencil" size={14} /> Edit details
                    </button>
                    <button role="menuitem" onClick={() => { setMenuOpen(false); onArchive(); }}>
                      <Icon name="archive" size={14} /> Archive
                    </button>
                    <button role="menuitem" className="danger" onClick={() => { setMenuOpen(false); onDelete(); }}>
                      <Icon name="trash" size={14} /> Delete
                    </button>
                  </div>
                )}
              </div>
            </div>
          </div>

          <div className="project-composer">{composer}</div>

          <div className="project-home-hint">
            <Icon name="note" size={18} />
            <span>Give the assistant a task and it'll pick up your project context automatically.</span>
          </div>
        </div>

        <aside className="project-rail">
          <section className="rail-card">
            <div className="rail-card-head">
              <span className="rail-card-title">Instructions</span>
              <button className="rail-card-edit" aria-label="Edit instructions" onClick={onEditInstructions}>
                <Icon name="pencil" size={14} />
              </button>
            </div>
            <p className="rail-card-body">
              {instrPreview || "Add instructions to tailor responses for chats in this project."}
            </p>
          </section>

          <section className="rail-card">
            <div className="rail-card-head">
              <span className="rail-card-title">Memory</span>
              <span className="rail-badge"><Icon name="pin-angle" size={11} /> Only you</span>
            </div>
            <p className="rail-card-body">
              {memory.trim() || "Project memory will show here after a few chats."}
            </p>
            {memory.trim() && memoryUpdated && (
              <div className="rail-card-foot">Updated {memoryUpdated}</div>
            )}
          </section>

          <section className="rail-card">
            <div className="rail-card-head">
              <span className="rail-card-title">Context</span>
              <ContextAdd onUploadClick={() => fileRef.current?.click()} onAddText={onAddText} />
            </div>
            <input
              ref={fileRef}
              type="file"
              hidden
              onChange={(e) => {
                const f = e.target.files?.[0];
                if (f) onUploadFile(f);
                e.target.value = "";
              }}
            />
            {files.length === 0 ? (
              <div className="rail-context-empty">
                Add PDFs, documents, or other text to reference in this project.
              </div>
            ) : (
              <div className="rail-files">
                {files.map((f) => (
                  <div className="rail-file" key={f.name} title={f.name}>
                    <span className="rail-file-badge">{f.badge}</span>
                    <span className="rail-file-name">{f.name}</span>
                    <button
                      className="rail-file-del"
                      title="Remove from project knowledge"
                      aria-label={`Remove ${f.name}`}
                      onClick={() => onRemoveFile(f.name)}
                    >
                      ✕
                    </button>
                  </div>
                ))}
              </div>
            )}
          </section>
        </aside>
      </div>
    </div>
  );
}

// The Context "+" menu: upload a file from the device, or paste text content.
function ContextAdd({ onUploadClick, onAddText }: { onUploadClick: () => void; onAddText: () => void }) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    function onDoc(e: MouseEvent) {
      if (!ref.current?.contains(e.target as Node)) setOpen(false);
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") setOpen(false);
    }
    document.addEventListener("mousedown", onDoc);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDoc);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);
  return (
    <div className="rail-add" ref={ref}>
      <button className="rail-card-edit" aria-label="Add context" aria-expanded={open}
              onClick={() => setOpen((o) => !o)}>
        <Icon name="plus" size={15} />
      </button>
      {open && (
        <div className="card-menu" role="menu">
          <button role="menuitem" onClick={() => { setOpen(false); onUploadClick(); }}>
            <Icon name="cloud-up" size={14} /> Upload from device
          </button>
          <button role="menuitem" onClick={() => { setOpen(false); onAddText(); }}>
            <Icon name="note" size={14} /> Add text content
          </button>
        </div>
      )}
    </div>
  );
}
