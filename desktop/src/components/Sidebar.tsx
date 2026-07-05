import { useState } from "react";

import type { ConversationSummary, Project } from "../api/client";
import { Icon } from "./Icon";

export type SurfaceView = "chat" | "cowork" | "code";

// The app sidebar: surface switcher (Chat / Cowork / Code) at the top, primary nav
// (New chat, Projects, Customize), a flat Recents list (pinned first) with hover
// actions and inline rename, and the workspace footer. All conversation/project
// functions survive: switch/create/manage project, open/rename/pin/delete.
export function Sidebar({
  view,
  onView,
  projects,
  activeProject,
  onSelectProject,
  onNewProject,
  onManageProject,
  list,
  currentId,
  err,
  onNew,
  onOpen,
  onDelete,
  onRename,
  onTogglePin,
  onCustomize,
  modelLabel,
}: {
  view: SurfaceView;
  onView: (v: SurfaceView) => void;
  projects: Project[];
  activeProject: string | null;
  onSelectProject: (pid: string | null) => void;
  onNewProject: (name: string) => void;
  onManageProject: () => void;
  list: ConversationSummary[];
  currentId: string | null;
  err?: string | null;
  onNew: () => void;
  onOpen: (cid: string, pid: string) => void;
  onDelete: (cid: string, pid: string) => void;
  onRename: (cid: string, pid: string, title: string) => void;
  onTogglePin: (cid: string, pid: string, pinned: boolean) => void;
  onCustomize: () => void;
  modelLabel: string;
}) {
  const [projectsOpen, setProjectsOpen] = useState(false);
  const [newProjectDraft, setNewProjectDraft] = useState<string | null>(null);
  const [renaming, setRenaming] = useState<{ id: string; draft: string } | null>(null);
  const activeName = projects.find((p) => p.id === activeProject)?.name;
  // Flat Recents, pinned chats first (matching the desktop pattern).
  const recents = [...list.filter((c) => c.pinned), ...list.filter((c) => !c.pinned)];

  function commitNewProject() {
    const name = (newProjectDraft ?? "").trim();
    if (name) onNewProject(name);
    setNewProjectDraft(null);
  }

  function commitRename(c: ConversationSummary, pid: string) {
    const title = (renaming?.draft ?? "").trim();
    if (title && title !== c.title) onRename(c.id, pid, title);
    setRenaming(null);
  }

  return (
    <aside className="sidebar">
      <div className="side-tabs" role="tablist" aria-label="Surface">
        {(["chat", "cowork", "code"] as const).map((v) => (
          <button
            key={v}
            role="tab"
            aria-selected={view === v}
            className={`side-tab ${view === v ? "active" : ""}`}
            onClick={() => onView(v)}
          >
            {v === "chat" ? "Chat" : v === "cowork" ? "Cowork" : "Code"}
          </button>
        ))}
      </div>

      <nav className="side-nav">
        <button className="side-row primary" onClick={onNew}>
          <span className="side-ic accent"><Icon name="pencil" /></span>
          {view === "cowork" ? "New task" : "New chat"}
        </button>
        <button
          className="side-row"
          aria-expanded={projectsOpen}
          onClick={() => setProjectsOpen((o) => !o)}
        >
          <span className="side-ic"><Icon name="folder" /></span> Projects
          {activeName && <span className="side-current">{activeName}</span>}
          <span className="side-caret">{projectsOpen ? "▾" : "▸"}</span>
        </button>
        {projectsOpen && (
          <div className="project-flyout">
            <button
              className={`project-row ${activeProject === null ? "active" : ""}`}
              onClick={() => onSelectProject(null)}
            >
              General
            </button>
            {projects.map((p) => (
              <button
                key={p.id}
                className={`project-row ${p.id === activeProject ? "active" : ""}`}
                onClick={() => onSelectProject(p.id)}
              >
                {p.name}
              </button>
            ))}
            {newProjectDraft === null ? (
              <button className="project-row new" onClick={() => setNewProjectDraft("")}>
                ＋ New project…
              </button>
            ) : (
              // Cancel only when focus leaves the whole row — Tab from the input to
              // the Add button must not discard the draft (keyboard path).
              <div
                className="project-new-row"
                onBlur={(e) => {
                  if (!e.currentTarget.contains(e.relatedTarget as Node)) setNewProjectDraft(null);
                }}
              >
                <input
                  className="project-new-input"
                  autoFocus
                  placeholder="Project name"
                  aria-label="New project name"
                  value={newProjectDraft}
                  onChange={(e) => setNewProjectDraft(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") commitNewProject();
                    if (e.key === "Escape") setNewProjectDraft(null);
                  }}
                />
                {/* mousedown fires before the input's blur — the click always lands. */}
                <button
                  className="project-new-add"
                  aria-label="Create project"
                  disabled={!(newProjectDraft ?? "").trim()}
                  onMouseDown={(e) => e.preventDefault()}
                  onClick={commitNewProject}
                >
                  Add
                </button>
              </div>
            )}
            {activeProject && (
              <button className="project-row manage" onClick={onManageProject}>
                Manage “{activeName}”
              </button>
            )}
          </div>
        )}
        <button className="side-row" onClick={onCustomize}>
          <span className="side-ic"><Icon name="sliders" /></span> Customize
        </button>
      </nav>

      <div className="side-recents">
        <div className="side-label">Recents</div>
        {err && <div className="side-err" role="alert">{err}</div>}
        {recents.map((c) => {
          const pid = c.project_id ?? "general";
          const isRenaming = renaming?.id === c.id;
          return (
            <div
              key={c.id}
              className={`conv-item ${c.id === currentId ? "active" : ""}`}
              onClick={() => !isRenaming && onOpen(c.id, pid)}
            >
              {c.pinned && (
                <span className="conv-pin" aria-hidden="true">
                  <Icon name="pin-filled" size={12} />
                </span>
              )}
              {isRenaming ? (
                <input
                  className="conv-rename-input"
                  autoFocus
                  aria-label="Rename conversation"
                  value={renaming.draft}
                  onChange={(e) => setRenaming({ id: c.id, draft: e.target.value })}
                  onClick={(e) => e.stopPropagation()}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") commitRename(c, pid);
                    if (e.key === "Escape") setRenaming(null);
                  }}
                  onBlur={() => setRenaming(null)}
                />
              ) : (
                <span className="conv-title" title={c.title}>
                  {c.title || "Untitled"}
                </span>
              )}
              {!isRenaming && c.project_id && c.project_id !== "general" && (
                <span className="conv-proj" title={c.project_name}>
                  {c.project_name}
                </span>
              )}
              <span className="conv-actions">
                <button
                  className="conv-act"
                  title={c.pinned ? "Unpin" : "Pin"}
                  aria-label={c.pinned ? `Unpin ${c.title || "Untitled"}` : `Pin ${c.title || "Untitled"}`}
                  onClick={(e) => {
                    e.stopPropagation();
                    onTogglePin(c.id, pid, !c.pinned);
                  }}
                >
                  <Icon name={c.pinned ? "pin-filled" : "pin"} size={13} />
                </button>
                <button
                  className="conv-act"
                  title="Rename"
                  aria-label={`Rename ${c.title || "Untitled"}`}
                  onClick={(e) => {
                    e.stopPropagation();
                    setRenaming({ id: c.id, draft: c.title || "" });
                  }}
                >
                  <Icon name="pencil" size={13} />
                </button>
                <button
                  className="conv-act conv-del"
                  title="Delete"
                  aria-label={`Delete ${c.title || "Untitled"}`}
                  onClick={(e) => {
                    e.stopPropagation();
                    onDelete(c.id, pid);
                  }}
                >
                  <Icon name="x" size={13} />
                </button>
              </span>
            </div>
          );
        })}
        {recents.length === 0 && <div className="conv-empty">No conversations yet</div>}
      </div>

      <button className="side-foot" onClick={onCustomize} title="Settings">
        <span className="side-avatar" aria-hidden="true" />
        <span className="side-foot-meta">
          <span className="side-foot-name">Workspace</span>
          <span className="side-foot-sub">{modelLabel}</span>
        </span>
        <span className="side-caret">⌄</span>
      </button>
    </aside>
  );
}
