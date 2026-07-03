import { type ConversationSummary, GENERAL_PROJECT } from "../api/client";

// Conversations belonging to a given project scope. `null` (or "general") means the
// implicit General space: items with no project_id or the general project.
export function conversationsForProject(
  list: ConversationSummary[],
  projectId: string | null,
): ConversationSummary[] {
  const pid = projectId ?? GENERAL_PROJECT;
  if (pid === GENERAL_PROJECT) {
    return list.filter((c) => !c.project_id || c.project_id === GENERAL_PROJECT);
  }
  return list.filter((c) => c.project_id === pid);
}
