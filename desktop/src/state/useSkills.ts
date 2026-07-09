// Loads the available Agent Skills, and manages importing new ones (upload a .md or
// sync a git repo of skills) + removing user-imported ones. The composer's slash-command
// autocomplete and the Settings Skills directory both read `list`.

import { useCallback, useEffect, useState } from "react";

import { type SkillSummary, skills as skillsApi } from "../api/client";

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

  // Import a skill from an uploaded markdown file. Returns an error message or null.
  const importFile = useCallback(
    async (filename: string, content: string): Promise<string | null> => {
      setBusy(true);
      setErr(null);
      try {
        await skillsApi.import(filename, content);
        await refresh();
        return null;
      } catch (e) {
        return e instanceof Error ? e.message : String(e);
      } finally {
        setBusy(false);
      }
    },
    [refresh],
  );

  // Sync skills from a git repository. Returns an error message or null.
  const importFromRepo = useCallback(
    async (url: string, ref = ""): Promise<string | null> => {
      setBusy(true);
      setErr(null);
      try {
        await skillsApi.importFromRepo(url, ref);
        await refresh();
        return null;
      } catch (e) {
        return e instanceof Error ? e.message : String(e);
      } finally {
        setBusy(false);
      }
    },
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

  return { list, err, busy, refresh, importFile, importFromRepo, remove };
}
