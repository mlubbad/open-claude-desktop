// Fetches the branch family (the tree of conversations linked by parent_id) for the
// open conversation, so the transcript can show a switcher when a chat has siblings or
// children. Returns null for a draft/incognito chat, while offline, or on any fetch
// error — the switcher simply doesn't render in those cases.
//
// Keyed on the conversation id: opening another chat (including navigating to a freshly
// created branch) refetches, so the bar always reflects the family of what's on screen.

import { useEffect, useState } from "react";

import { type BranchFamily, conversations as convApi } from "../api/client";

export function useBranchFamily(
  current: { cid: string; pid: string } | null,
  enabled: boolean,
): BranchFamily | null {
  const [family, setFamily] = useState<BranchFamily | null>(null);
  const cid = current?.cid ?? null;
  const pid = current?.pid ?? null;
  useEffect(() => {
    if (!enabled || !cid || !pid) {
      setFamily(null);
      return;
    }
    let live = true;
    convApi
      .branches(pid, cid)
      .then((f) => {
        if (live) setFamily(f);
      })
      .catch(() => {
        if (live) setFamily(null);
      });
    return () => {
      live = false;
    };
  }, [cid, pid, enabled]);
  return family;
}
