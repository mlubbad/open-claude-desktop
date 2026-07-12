// MCP prompts as slash commands (P1-2): prompts published by enabled, connected
// MCP servers surface in the composer's `/` menu as `/server:prompt`, alongside
// Agent Skills. Selecting one renders the prompt server-side and inserts its text.

import { useEffect, useState } from "react";

import { mcp } from "../api/client";

export interface McpSlashPrompt {
  name: string; // namespaced for the slash menu: "<serverId>:<promptName>"
  description?: string;
  sid: string;
  prompt: string; // the prompt's own name on the server
}

export function useMcpPrompts(
  servers: { id: string; status: string }[],
  enabled: string[],
): McpSlashPrompt[] {
  const [prompts, setPrompts] = useState<McpSlashPrompt[]>([]);
  // Refetch only when the set of usable servers actually changes, not on every
  // poll-driven identity change of the servers array.
  const key = servers
    .filter((s) => s.status === "connected" && enabled.includes(s.id))
    .map((s) => s.id)
    .sort()
    .join(",");

  useEffect(() => {
    let alive = true;
    if (!key) {
      setPrompts([]);
      return;
    }
    void Promise.all(
      key.split(",").map((sid) =>
        mcp
          .prompts(sid)
          .then((r) =>
            (r.prompts ?? []).map((p) => ({
              name: `${sid}:${p.name}`,
              description: p.description,
              sid,
              prompt: p.name,
            })),
          )
          .catch(() => [] as McpSlashPrompt[]),
      ),
    ).then((all) => {
      if (alive) setPrompts(all.flat());
    });
    return () => {
      alive = false;
    };
  }, [key]);

  return prompts;
}
