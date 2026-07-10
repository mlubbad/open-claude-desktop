import { useState } from "react";

import { useDialogEscape } from "./useDialogEscape";

// Shared "sync from a git URL" modal used by the Skills and Plugins directories.
export function RepoSyncModal({
  title,
  blurb,
  allowRemote,
  onSync,
  onClose,
}: {
  title: string;
  blurb: string;
  allowRemote: boolean;
  onSync: (url: string, ref: string) => Promise<string | null>;
  onClose: () => void;
}) {
  const [url, setUrl] = useState("");
  const [ref, setRef] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  useDialogEscape(onClose); // Escape closes only this dialog, not the whole Settings modal

  async function submit() {
    if (!url.trim()) return;
    setBusy(true);
    setErr(null);
    const failure = await onSync(url.trim(), ref.trim());
    setBusy(false);
    if (failure) setErr(failure);
    else onClose();
  }

  return (
    <div className="settings-overlay" onClick={onClose}>
      <div
        className="add-market-modal"
        role="dialog"
        aria-modal="true"
        aria-label={title}
        onClick={(e) => e.stopPropagation()}
      >
        <header className="add-market-head">
          <h2>{title}</h2>
          <button className="settings-close" aria-label="Close" title="Close" onClick={onClose}>✕</button>
        </header>
        <div className="add-market-form">
          <p className="settings-hint" style={{ margin: "0 0 10px" }}>{blurb}</p>
          {!allowRemote && (
            <p className="settings-err">
              Remote syncing is disabled on this install (MARKETPLACE_ALLOW_REMOTE=0).
            </p>
          )}
          {err && <div className="settings-err">{err}</div>}
          <label className="field-label" htmlFor="rs-url">Repository URL</label>
          <input id="rs-url" placeholder="https://github.com/owner/repo.git"
                 value={url} onChange={(e) => setUrl(e.target.value)} />
          <label className="field-label" htmlFor="rs-ref">Branch or tag (optional)</label>
          <input id="rs-ref" placeholder="main" value={ref} onChange={(e) => setRef(e.target.value)} />
          <div className="drive-actions">
            <button className="btn-secondary" onClick={onClose}>Cancel</button>
            <button className="btn-primary" disabled={!url.trim() || busy || !allowRemote}
                    onClick={() => void submit()}>
              {busy ? "Syncing…" : "Sync"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
