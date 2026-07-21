// v1 offers file restore only: conversation restore is deferred (the backend
// RestoreBody accepts "files" | "both", but "both" without a conversation-restore
// implementation behaves identically to "files" -- so the menu only exposes that).
export function RewindMenu({
  turnId,
  onRestore,
}: {
  turnId: string;
  onRestore: (turnId: string, what: "files") => void;
}) {
  return (
    <div className="rewind-menu" role="menu">
      <button type="button" role="menuitem" onClick={() => onRestore(turnId, "files")}>
        Restore files to before this message
      </button>
    </div>
  );
}
