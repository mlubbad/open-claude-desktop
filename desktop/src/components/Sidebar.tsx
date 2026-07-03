import type { ConversationSummary } from "../api/client";

export function Sidebar({
  list,
  currentId,
  onNew,
  onOpen,
  onDelete,
}: {
  list: ConversationSummary[];
  currentId: string | null;
  onNew: () => void;
  onOpen: (cid: string, pid: string) => void;
  onDelete: (cid: string, pid: string) => void;
}) {
  return (
    <aside className="sidebar">
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
