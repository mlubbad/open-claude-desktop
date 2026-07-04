import { describe, expect, it } from "vitest";

import type { ConversationSummary } from "../api/client";
import { groupByRecency } from "./grouping";

// Fixed "now": 2026-07-04 12:00 local.
const NOW = new Date(2026, 6, 4, 12, 0, 0).getTime();
const DAY = 24 * 60 * 60 * 1000;

function conv(id: string, updatedMs: number, pinned = false): ConversationSummary {
  return { id, title: id, updated_at: new Date(updatedMs).toISOString(), pinned };
}

describe("groupByRecency", () => {
  it("buckets by calendar recency", () => {
    const todayStart = new Date(2026, 6, 4).getTime();
    const groups = groupByRecency(
      [
        conv("today", todayStart + 3 * 60 * 60 * 1000),
        conv("yesterday", todayStart - 2 * 60 * 60 * 1000),
        conv("lastweek", todayStart - 4 * DAY),
        conv("ancient", todayStart - 30 * DAY),
      ],
      NOW,
    );
    const labels = groups.map((g) => g.label);
    expect(labels).toEqual(["Today", "Yesterday", "Previous 7 Days", "Older"]);
    expect(groups[0].items[0].id).toBe("today");
    expect(groups[3].items[0].id).toBe("ancient");
  });

  it("puts pinned chats in their own top section", () => {
    const groups = groupByRecency([conv("p", NOW, true), conv("t", NOW)], NOW);
    expect(groups[0].label).toBe("Pinned");
    expect(groups[0].items[0].id).toBe("p");
    expect(groups[1].label).toBe("Today");
  });

  it("omits empty sections", () => {
    const groups = groupByRecency([conv("t", NOW)], NOW);
    expect(groups.map((g) => g.label)).toEqual(["Today"]);
  });

  it("treats an unparseable timestamp as Older", () => {
    const bad = { id: "x", title: "x", updated_at: "", pinned: false };
    const groups = groupByRecency([bad], NOW);
    expect(groups[0].label).toBe("Older");
  });

  it("returns nothing for an empty list", () => {
    expect(groupByRecency([], NOW)).toEqual([]);
  });
});
