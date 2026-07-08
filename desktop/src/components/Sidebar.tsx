import { useState } from "react";

import type { ConversationSummary, Project } from "../api/client";
import { ConvMenu } from "./ConvMenu";
import { Icon } from "./Icon";

export type SurfaceView = "chat" | "cowork" | "code";

// The app sidebar: surface switcher (Chat / Cowork / Code) at the top, primary nav
// (New chat, Projects, Artifacts, Customize), a distinct Pinned section above the
// Recents list, each row carrying a ⋮ overflow menu (pin/rename/move/delete), and
// the workspace footer. All conversation/project functions survive.
export function Sidebar({
  view,
  onView,
  projects,
  activeProject,
  projectsActive,
  onProjects,
  onOpenProject,
  onArtifacts,
  list,
  currentId,
  err,
  onNew,
  onOpen,
  onDelete,
  onRename,
  onTogglePin,
  onMove,
  onCustomize,
  modelLabel,
}: {
  view: SurfaceView;
  onView: (v: SurfaceView) => void;
  projects: Project[];
  activeProject: string | null;
  projectsActive: boolean;
  onProjects: () => void;
  onOpenProject: (pid: string) => void;
  onArtifacts: () => void;
  list: ConversationSummary[];
  currentId: string | null;
  err?: string | null;
  onNew: () => void;
  onOpen: (cid: string, pid: string) => void;
  onDelete: (cid: string, pid: string) => void;
  onRename: (cid: string, pid: string, title: string) => void;
  onTogglePin: (cid: string, pid: string, pinned: boolean) => void;
  onMove: (cid: string, pid: string, dstProjectId: string) => void;
  onCustomize: () => void;
  modelLabel: string;
}) {
  const [renaming, setRenaming] = useState<{ id: string; draft: string } | null>(null);
  const [menuFor, setMenuFor] = useState<string | null>(null); // conv id with its ⋮ menu open
  const [pinnedOpen, setPinnedOpen] = useState(true);
  // Pinned chats get their own section above Recents; the rest stay in Recents.
  const pinned = list.filter((c) => c.pinned);
  const recents = list.filter((c) => !c.pinned);
  const pinnedProjects = projects.filter((p) => p.pinned);

  function commitRename(c: ConversationSummary, pid: string) {
    const title = (renaming?.draft ?? "").trim();
    if (title && title !== c.title) onRename(c.id, pid, title);
    setRenaming(null);
  }

  // One recents/pinned row: title (RTL-aware), project tag, and the ⋮ overflow menu.
  function renderRow(c: ConversationSummary) {
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
          <span className="conv-title" title={c.title} dir="auto">
            {c.title || "Untitled"}
          </span>
        )}
        {!isRenaming && c.project_id && c.project_id !== "general" && (
          <span className="conv-proj" title={c.project_name}>
            {c.project_name}
          </span>
        )}
        <div className="conv-menu-anchor2">
          <button
            className="conv-act conv-more"
            title="More"
            aria-label={`Actions for ${c.title || "Untitled"}`}
            aria-haspopup="menu"
            aria-expanded={menuFor === c.id}
            onClick={(e) => {
              e.stopPropagation();
              setMenuFor((m) => (m === c.id ? null : c.id));
            }}
          >
            <Icon name="dots" size={15} />
          </button>
          {menuFor === c.id && (
            <ConvMenu
              pinned={c.pinned}
              inProject={!!c.project_id && c.project_id !== "general"}
              projects={projects}
              currentProjectId={pid}
              onPin={() => onTogglePin(c.id, pid, !c.pinned)}
              onRename={() => setRenaming({ id: c.id, draft: c.title || "" })}
              onMove={(dst) => onMove(c.id, pid, dst)}
              onDelete={() => onDelete(c.id, pid)}
              onClose={() => setMenuFor(null)}
            />
          )}
        </div>
      </div>
    );
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
          className={`side-row ${projectsActive ? "active" : ""}`}
          aria-current={projectsActive ? "page" : undefined}
          onClick={onProjects}
        >
          <span className="side-ic"><Icon name="folder" /></span> Projects
        </button>
        {pinnedProjects.length > 0 && (
          <div className="side-pinned-projects">
            {pinnedProjects.map((p) => (
              <button
                key={p.id}
                className={`project-row ${p.id === activeProject ? "active" : ""}`}
                title={p.name}
                onClick={() => onOpenProject(p.id)}
              >
                <span className="project-row-pin" aria-hidden="true"><Icon name="pin-filled" size={11} /></span>
                <span className="project-row-name">{p.name}</span>
              </button>
            ))}
          </div>
        )}
        <button className="side-row" onClick={onArtifacts}>
          <span className="side-ic"><Icon name="panel" /></span> Artifacts
        </button>
        <button className="side-row" onClick={onCustomize}>
          <span className="side-ic"><Icon name="sliders" /></span> Customize
        </button>
      </nav>

      <div className="side-recents">
        {err && <div className="side-err" role="alert">{err}</div>}

        {pinned.length > 0 && (
          <>
            <button className="side-label side-label-btn" aria-expanded={pinnedOpen}
                    onClick={() => setPinnedOpen((o) => !o)}>
              <span className={`side-label-chev ${pinnedOpen ? "" : "collapsed"}`} aria-hidden="true">
                <Icon name="chev-down" size={11} />
              </span>
              Pinned
            </button>
            {pinnedOpen && pinned.map(renderRow)}
          </>
        )}

        <div className="side-label">Recents</div>
        {recents.map(renderRow)}
        {list.length === 0 && <div className="conv-empty">No conversations yet</div>}
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
