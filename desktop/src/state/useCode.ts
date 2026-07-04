// Code workspace state: the file tree and the currently-open file. Refreshes on demand
// (e.g. after an agent turn that may have edited files).

import { useCallback, useEffect, useState } from "react";

import { type CodeFile, code as codeApi } from "../api/client";
import { buildTree, type TreeNode } from "./codeTree";

export function useCode(project: string | undefined, active: boolean) {
  const [tree, setTree] = useState<TreeNode[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [file, setFile] = useState<CodeFile | null>(null);
  const [err, setErr] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    if (!active) return;
    try {
      const r = await codeApi.tree(project);
      setTree(buildTree(r.entries));
      setErr(null);
    } catch (e) {
      setErr(String(e));
    }
  }, [active, project]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const open = useCallback(
    async (path: string) => {
      setSelected(path);
      try {
        setFile(await codeApi.file(path, project));
      } catch (e) {
        setErr(String(e));
      }
    },
    [project],
  );

  // Re-open the current file (after an edit) to show fresh content.
  const reopen = useCallback(() => {
    if (selected) void open(selected);
  }, [selected, open]);

  return { tree, selected, file, err, refresh, open, reopen };
}
