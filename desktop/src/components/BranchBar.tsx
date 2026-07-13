import type { BranchFamily } from "../api/client";
import { Icon } from "./Icon";

// A compact switcher shown at the top of the transcript when the open conversation
// belongs to a branch family (more than one node). Branching forks a conversation into
// a sibling that shares history up to the fork point, so a family is a small tree; this
// bar lets you hop between its members. It renders nothing for a lone conversation —
// the parent gates on `family.nodes.length > 1`.
//
// Ordering: the root (the original, un-forked chat) leads, then the rest in the order
// the backend returned (oldest-updated first) for a stable list that never reshuffles
// as you switch. The active node is marked and non-clickable.
export function BranchBar({
  family,
  current,
  onSwitch,
}: {
  family: BranchFamily;
  current: string | null;
  onSwitch: (cid: string, pid: string) => void;
}) {
  const ordered = [...family.nodes].sort((a, b) => {
    if (a.id === family.root) return -1;
    if (b.id === family.root) return 1;
    return 0;
  });
  return (
    <div className="branch-bar" role="group" aria-label="Conversation branches">
      <span className="branch-bar-lead" aria-hidden="true">
        <Icon name="branch" size={13} />
        {family.nodes.length} branches
      </span>
      <div className="branch-chips">
        {ordered.map((n) => {
          const active = n.id === current;
          const isRoot = n.id === family.root;
          const sub = isRoot ? "main" : `fork @ ${(n.fork_index ?? 0) + 1}`;
          return (
            <button
              key={n.id}
              className={`branch-chip ${active ? "active" : ""}`}
              aria-current={active ? "true" : undefined}
              disabled={active}
              title={active ? "Current branch" : `Switch to “${n.title}”`}
              onClick={() => onSwitch(n.id, n.project_id)}
            >
              <span className="branch-chip-title">{n.title || "Untitled"}</span>
              <span className="branch-chip-sub">{sub}</span>
            </button>
          );
        })}
      </div>
    </div>
  );
}
