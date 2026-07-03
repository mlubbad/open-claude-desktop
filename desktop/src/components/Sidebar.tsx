import type { ConversationSummary, Project } from "../api/client";

export function Sidebar({
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
}: {
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
}) {
  return (
    <aside className="sidebar">
      <div className="project-select">
        <select
          value={activeProject ?? "__general"}
          onChange={(e) => {
            const v = e.target.value;
            if (v === "__new") onNewProject();
            else onSelectProject(v === "__general" ? null : v);
          }}
        >
          <option value="__general">General</option>
          {projects.map((p) => (
            <option key={p.id} value={p.id}>
              {p.name}
            </option>
          ))}
          <option value="__new">+ New project…</option>
        </select>
        {activeProject && (
          <button className="manage-project" title="Manage project" onClick={onManageProject}>
            ⚙
          </button>
        )}
      </div>

      <button className="new-chat" onClick={onNew}>
        + New chat
      </button>

      <nav className="conv-list">
        {list.map((c) => (
          <div
            key={c.id}
            className={`conv-item ${c.id === currentId ? "active" : ""}`}
            onClick={() => onOpen(c.id, c.project_id ?? "general")}
          >
            <span className="conv-title" title={c.title}>
              {c.pinned ? "★ " : ""}
              {c.title || "Untitled"}
            </span>
            <button
              className="conv-del"
              title="Delete"
              onClick={(e) => {
                e.stopPropagation();
                onDelete(c.id, c.project_id ?? "general");
              }}
            >
              ✕
            </button>
          </div>
        ))}
        {list.length === 0 && <div className="conv-empty">No conversations yet</div>}
      </nav>
    </aside>
  );
}
