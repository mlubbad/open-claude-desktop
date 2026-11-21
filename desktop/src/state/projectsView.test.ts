import { describe, expect, it } from "vitest";

import type { Project } from "../api/client";
import { filterSortProjects, SORT_LABELS } from "./projectsView";

const P = (over: Partial<Project> & { id: string }): Project => ({
  name: over.id,
  ...over,
});

const list: Project[] = [
  P({ id: "beta", name: "Beta", description: "clicks data", updated_at: "2026-02-01", created_at: "2026-01-10" }),
  P({ id: "alpha", name: "Alpha", description: "travel", updated_at: "2026-03-01", created_at: "2026-01-20", pinned: true }),
  P({ id: "gamma", name: "Gamma", description: "", updated_at: "2026-01-01", created_at: "2026-01-30" }),
];

describe("filterSortProjects", () => {
  it("sorts by last updated (desc) with pinned floated to the top", () => {
    // alpha is pinned → first; then by updated desc among the rest: beta, gamma.
    expect(filterSortProjects(list, "", "updated").map((p) => p.id)).toEqual(["alpha", "beta", "gamma"]);
  });

  it("sorts alphabetically", () => {
    // alpha pinned leads; remaining sorted A→Z: beta, gamma.
    expect(filterSortProjects(list, "", "name").map((p) => p.id)).toEqual(["alpha", "beta", "gamma"]);
  });

  it("sorts by recently created (desc), pinned still first", () => {
    expect(filterSortProjects(list, "", "created").map((p) => p.id)).toEqual(["alpha", "gamma", "beta"]);
  });

  it("filters by name or description, case-insensitively", () => {
    expect(filterSortProjects(list, "CLICKS", "updated").map((p) => p.id)).toEqual(["beta"]);
    expect(filterSortProjects(list, "al", "updated").map((p) => p.id)).toEqual(["alpha"]);
    expect(filterSortProjects(list, "zzz", "updated")).toEqual([]);
  });

  it("exposes human sort labels", () => {
    expect(SORT_LABELS.updated).toBe("Last updated");
    expect(SORT_LABELS.name).toBe("Alphabetical");
  });
});
