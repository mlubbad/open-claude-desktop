import { describe, expect, it } from "vitest";

import type { ConversationSummary } from "../api/client";
import { conversationsForProject } from "./projectFilter";

const conv = (id: string, project_id?: string): ConversationSummary => ({
  id,
  title: id,
  updated_at: "",
  pinned: false,
  project_id,
});

const list = [conv("a"), conv("b", "general"), conv("c", "proj1"), conv("d", "proj2")];

describe("conversationsForProject", () => {
  it("General scope includes items with no project or the general project", () => {
    const ids = conversationsForProject(list, null).map((c) => c.id);
    expect(ids).toEqual(["a", "b"]);
  });

  it("a project scope includes only that project's conversations", () => {
    expect(conversationsForProject(list, "proj1").map((c) => c.id)).toEqual(["c"]);
    expect(conversationsForProject(list, "proj2").map((c) => c.id)).toEqual(["d"]);
  });
});
