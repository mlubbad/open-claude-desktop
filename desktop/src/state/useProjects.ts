// Project management: the list, the active project (null = General), create/delete,
// and lazy loading of a project's instructions, knowledge files, and capacity.

import { useCallback, useEffect, useState } from "react";

import {
  type Capacity,
  type Project,
  type ProjectFile,
  type ProjectPatch,
  projects as projectApi,
} from "../api/client";

export function useProjects() {
  const [list, setList] = useState<Project[]>([]);
  const [active, setActive] = useState<string | null>(null); // null = General
  const [err, setErr] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      setList(await projectApi.list());
      setErr(null); // recovery clears the sidebar alert — errors never stick
    } catch (e) {
      setErr(String(e));
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const create = useCallback(
    async (name: string, description = ""): Promise<string | null> => {
      try {
        const p = await projectApi.create(name, description);
        await refresh();
        setActive(p.id);
        return p.id;
      } catch (e) {
        setErr(String(e));
        return null;
      }
    },
    [refresh],
  );

  // Patch a project's details/state (edit name+description, pin, archive). Optimistic:
  // updates the local list immediately, then reconciles from the server.
  const update = useCallback(
    async (pid: string, patch: ProjectPatch) => {
      setList((l) => l.map((p) => (p.id === pid ? { ...p, ...patch } : p)));
      try {
        await projectApi.update(pid, patch);
      } catch (e) {
        setErr(String(e));
      }
      await refresh();
    },
    [refresh],
  );

  const remove = useCallback(
    async (pid: string) => {
      try {
        await projectApi.del(pid);
      } catch (e) {
        setErr(String(e));
      }
      if (active === pid) setActive(null);
      await refresh();
    },
    [active, refresh],
  );

  return { list, active, setActive, create, update, remove, refresh, err };
}

// A separate hook for the project home / manage panel: instructions, memory, files,
// capacity, plus upload + paste-text-as-file.
export function useProjectDetail(pid: string | null) {
  const [instructions, setInstructions] = useState("");
  const [memory, setMemory] = useState("");
  const [memoryUpdated, setMemoryUpdated] = useState("");
  const [files, setFiles] = useState<ProjectFile[]>([]);
  const [capacity, setCapacity] = useState<Capacity | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    if (!pid) return;
    try {
      const [instr, mem, fs, cap] = await Promise.all([
        projectApi.getInstructions(pid),
        projectApi.getMemory(pid),
        projectApi.files(pid),
        projectApi.capacity(pid),
      ]);
      setInstructions(instr.content);
      setMemory(mem.content);
      setMemoryUpdated(mem.updated_rel);
      setFiles(fs);
      setCapacity(cap);
    } catch {
      /* ignore */
    }
  }, [pid]);

  useEffect(() => {
    // Reset before (re)loading so a switch never shows the previous project's data
    // labeled as the new one (pid=null clears to empty).
    setInstructions("");
    setMemory("");
    setMemoryUpdated("");
    setFiles([]);
    setCapacity(null);
    void load();
  }, [load]);

  const saveInstructions = useCallback(
    async (content: string) => {
      if (!pid) return;
      setInstructions(content);
      try {
        await projectApi.saveInstructions(pid, content);
      } catch {
        /* ignore */
      }
    },
    [pid],
  );

  const upload = useCallback(
    async (file: File) => {
      if (!pid) return;
      setBusy(true);
      try {
        await projectApi.uploadFile(pid, file);
        await load();
      } catch {
        /* ignore */
      } finally {
        setBusy(false);
      }
    },
    [pid, load],
  );

  // "Add text content": save pasted text into the project's knowledge as a .txt file.
  const addText = useCallback(
    async (name: string, text: string) => {
      const safe = name.trim() || "note";
      const filename = /\.[a-z0-9]+$/i.test(safe) ? safe : `${safe}.txt`;
      await upload(new File([text], filename, { type: "text/plain" }));
    },
    [upload],
  );

  return {
    instructions,
    setInstructions,
    saveInstructions,
    memory,
    memoryUpdated,
    files,
    capacity,
    upload,
    addText,
    reload: load,
    busy,
  };
}
