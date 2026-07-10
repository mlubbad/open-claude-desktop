// Loads the available Agent Skills, and manages importing new ones (upload a .md or
// sync a git repo of skills) + removing user-imported ones. The composer's slash-command
// autocomplete and the Settings Skills directory both read `list`.

import { useCallback, useEffect, useState } from "react";

import { type SkillSummary, skills as skillsApi } from "../api/client";
import { runAction } from "./runAction";

export function useSkills() {
  const [list, setList] = useState<SkillSummary[]>([]);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const refresh = useCallback(async () => {
    try {
      setList(await skillsApi.list());
      setErr(null);
    } catch {
      setList([]);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  // These three share the same busy/clear-error/refresh shape; runAction clears err at
  // the start and returns the error message (or null) so the caller can surface it.
  // See state/runAction.ts.
  // Import a skill from an uploaded markdown file.
  const importFile = useCallback(
    (filename: string, content: string) =>
      runAction(() => skillsApi.import(filename, content), { setBusy, setErr, refresh }),
    [refresh],
  );

  // Import skills from a .zip of a skill folder (SKILL.md + references/) — the server
  // extracts it and imports like a synced repository.
  const importZip = useCallback(
    (file: File) => runAction(() => skillsApi.importZip(file), { setBusy, setErr, refresh }),
    [refresh],
  );

  // Sync skills from a git repository.
  const importFromRepo = useCallback(
    (url: string, ref = "") =>
      runAction(() => skillsApi.importFromRepo(url, ref), { setBusy, setErr, refresh }),
    [refresh],
  );

  const remove = useCallback(
    async (name: string) => {
      try {
        await skillsApi.remove(name);
        await refresh();
      } catch (e) {
        setErr(String(e));
      }
    },
    [refresh],
  );

  return { list, err, busy, refresh, importFile, importZip, importFromRepo, remove };
}
