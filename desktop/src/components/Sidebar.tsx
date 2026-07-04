import { useState } from "react";

import type { ConversationSummary, Project } from "../api/client";

export type SurfaceView = "chat" | "cowork" | "code";

// The app sidebar: surface switcher (Chat / Cowork / Code) at the top, primary nav
// (New chat, Projects, Customize), a flat Recents list (pinned first) with hover
// actions, and the workspace footer. All conversation/project functions from the
// previous sidebar survive: switch/create/manage project, open/rename/pin/delete.
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
  onNewProject: () => void;
  onManageProject: () => void;
  list: ConversationSummary[];
  currentId: string | null;
  onNew: () => void;
  onOpen: (cid: string, pid: string) => void;
  onDelete: (cid: string, pid: string) => void;
  onRename: (cid: string, pid: string, title: string) => void;
  onTogglePin: (cid: string, pid: string, pinned: boolean) => void;
  onCustomize: () => void;
  modelLabel: string;
}) {
  const [projectsOpen, setProjectsOpen] = useState(false);
  const activeName = projects.find((p) => p.id === activeProject)?.name;
  // Flat Recents, pinned chats first (matching the desktop pattern).
  const recents = [...list.filter((c) => c.pinned), ...list.filter((c) => !c.pinned)];

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
          <span className="side-ic accent">✎</span> {view === "cowork" ? "New task" : "New chat"}
        </button>
        <button
          className="side-row"
          aria-expanded={projectsOpen}
          onClick={() => setProjectsOpen((o) => !o)}
        >
          <span className="side-ic">▤</span> Projects
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
            <button className="project-row new" onClick={onNewProject}>
              ＋ New project…
            </button>
            {activeProject && (
              <button className="project-row manage" onClick={onManageProject}>
                Manage “{activeName}”
              </button>
            )}
          </div>
        )}
        <button className="side-row" onClick={onCustomize}>
          <span className="side-ic">✧</span> Customize
        </button>
      </nav>

      <div className="side-recents">
        <div className="side-label">Recents</div>
        {recents.map((c) => {
          const pid = c.project_id ?? "general";
          return (
            <div
              key={c.id}
              className={`conv-item ${c.id === currentId ? "active" : ""}`}
              onClick={() => onOpen(c.id, pid)}
            >
              <span className="conv-title" title={c.title}>
                {c.pinned ? "★ " : ""}
                {c.title || "Untitled"}
              </span>
              <span className="conv-actions">
                <button
                  className="conv-act"
                  title={c.pinned ? "Unpin" : "Pin"}
                  onClick={(e) => {
                    e.stopPropagation();
                    onTogglePin(c.id, pid, !c.pinned);
                  }}
                >
                  {c.pinned ? "★" : "☆"}
                </button>
                <button
                  className="conv-act"
                  title="Rename"
                  onClick={(e) => {
                    e.stopPropagation();
                    const next = window.prompt("Rename conversation", c.title || "");
                    if (next?.trim()) onRename(c.id, pid, next.trim());
                  }}
                >
                  ✎
                </button>
                <button
                  className="conv-act conv-del"
                  title="Delete"
                  onClick={(e) => {
                    e.stopPropagation();
                    onDelete(c.id, pid);
                  }}
                >
                  ✕
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
