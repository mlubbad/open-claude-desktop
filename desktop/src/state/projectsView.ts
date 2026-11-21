// Pure helpers for the Projects grid: search filtering + sort ordering. Framework-free
// and unit-tested so the page stays a thin renderer.

import type { Project } from "../api/client";

export type ProjectSort = "updated" | "created" | "name";

export const SORT_LABELS: Record<ProjectSort, string> = {
  updated: "Last updated",
  created: "Recently created",
  name: "Alphabetical",
};

const comparators: Record<ProjectSort, (a: Project, b: Project) => number> = {
  name: (a, b) => a.name.localeCompare(b.name),
  created: (a, b) => (b.created_at ?? "").localeCompare(a.created_at ?? ""),
  updated: (a, b) => (b.updated_at ?? "").localeCompare(a.updated_at ?? ""),
};

// Filter by a case-insensitive name/description match, sort by the chosen mode, then
// float pinned projects to the top (preserving order within each group) — matching
// Claude Desktop's grid, where pinned projects lead.
export function filterSortProjects(list: Project[], query: string, sort: ProjectSort): Project[] {
  const q = query.trim().toLowerCase();
  const filtered = q
    ? list.filter(
        (p) =>
          p.name.toLowerCase().includes(q) || (p.description ?? "").toLowerCase().includes(q),
      )
    : list.slice();
  filtered.sort(comparators[sort]);
  return [...filtered.filter((p) => p.pinned), ...filtered.filter((p) => !p.pinned)];
}
