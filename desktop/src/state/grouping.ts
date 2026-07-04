// Pure recency grouping for the sidebar chat list, mirroring Claude's Today / Yesterday
// / Previous 7 Days / Older sections. Pinned chats get their own section on top. `now`
// is injected so the logic is deterministic and testable.

import type { ConversationSummary } from "../api/client";

export interface ConvGroup {
  label: string;
  items: ConversationSummary[];
}

const DAY_MS = 24 * 60 * 60 * 1000;

// Local midnight (start of day) for a timestamp, so "Today"/"Yesterday" follow calendar
// days rather than rolling 24h windows.
function startOfDay(ms: number): number {
  const d = new Date(ms);
  return new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
}

function bucket(updatedMs: number, todayStart: number): string {
  if (updatedMs >= todayStart) return "Today";
  if (updatedMs >= todayStart - DAY_MS) return "Yesterday";
  if (updatedMs >= todayStart - 7 * DAY_MS) return "Previous 7 Days";
  return "Older";
}

const ORDER = ["Today", "Yesterday", "Previous 7 Days", "Older"];

export function groupByRecency(convs: ConversationSummary[], nowMs: number): ConvGroup[] {
  const pinned = convs.filter((c) => c.pinned);
  const rest = convs.filter((c) => !c.pinned);
  const todayStart = startOfDay(nowMs);

  const byLabel = new Map<string, ConversationSummary[]>();
  for (const c of rest) {
    const t = Date.parse(c.updated_at ?? "");
    const label = Number.isNaN(t) ? "Older" : bucket(t, todayStart);
    (byLabel.get(label) ?? byLabel.set(label, []).get(label)!).push(c);
  }

  const groups: ConvGroup[] = [];
  if (pinned.length) groups.push({ label: "Pinned", items: pinned });
  for (const label of ORDER) {
    const items = byLabel.get(label);
    if (items && items.length) groups.push({ label, items });
  }
  return groups;
}
