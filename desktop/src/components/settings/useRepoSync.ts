import { useCallback, useState } from "react";

// The url/ref + busy/error + submit state machine shared by the two "sync from a git
// URL" dialogs (RepoSyncModal for skills, AddMarketplaceModal for plugins). Both had
// this copy-pasted; the surrounding chrome differs (the marketplace variant adds a
// name field, a risk warning, and a choose-step), so they stay separate presentational
// components that share this logic. `onSync` returns an error message (or null on
// success, which closes the dialog).
export function useRepoSync(
  onSync: (url: string, ref: string) => Promise<string | null>,
  onClose: () => void,
) {
  const [url, setUrl] = useState("");
  const [ref, setRef] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const submit = useCallback(async () => {
    if (!url.trim()) return;
    setBusy(true);
    setErr(null);
    const failure = await onSync(url.trim(), ref.trim());
    setBusy(false);
    if (failure) setErr(failure);
    else onClose();
  }, [url, ref, onSync, onClose]);

  return { url, setUrl, ref, setRef, busy, err, submit };
}
