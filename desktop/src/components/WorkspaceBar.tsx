// A folder attached to the chat as a code workspace: name + a permission-mode selector
// (mirrors ocd_core.harness.rules' modes) + Detach. Rendered by the composer whenever a
// workspace is attached (see Composer.tsx's `workspace` prop).
export type WorkspaceMode = "default" | "acceptEdits" | "plan" | "strict" | "bypass";

const MODE_OPTIONS: { value: WorkspaceMode; label: string }[] = [
  { value: "default", label: "Ask" },
  { value: "acceptEdits", label: "Accept edits" },
  { value: "plan", label: "Plan" },
  { value: "strict", label: "Strict" },
  { value: "bypass", label: "Bypass" },
];

export function WorkspaceBar({
  root,
  mode,
  onModeChange,
  onDetach,
}: {
  root: string;
  mode: WorkspaceMode;
  onModeChange: (m: WorkspaceMode) => void;
  onDetach: () => void;
}) {
  const name = root.replace(/[/\\]+$/, "").split(/[/\\]/).pop() || root;
  return (
    <div className="workspace-bar">
      <span className="workspace-name" title={root}>
        <span aria-hidden="true">📁</span> {name}
      </span>
      <label className="workspace-mode-label">
        <span className="sr-only">Permission mode</span>
        <select
          aria-label="permission mode"
          value={mode}
          onChange={(e) => onModeChange(e.target.value as WorkspaceMode)}
        >
          {MODE_OPTIONS.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
      </label>
      <button type="button" className="workspace-detach" onClick={onDetach}>
        Detach
      </button>
    </div>
  );
}
