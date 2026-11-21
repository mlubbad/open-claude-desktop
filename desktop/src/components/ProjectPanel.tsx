import { type ChangeEvent, useRef } from "react";

import { useProjectDetail } from "../state/useProjects";

// Manage a project: custom instructions (injected into the system prompt for chats in
// this project) + knowledge files (RAG) with a capacity meter.
export function ProjectPanel({
  pid,
  name,
  onClose,
  onDelete,
}: {
  pid: string;
  name: string;
  onClose: () => void;
  onDelete: () => void;
}) {
  const { instructions, setInstructions, saveInstructions, files, capacity, upload, busy } =
    useProjectDetail(pid);
  const fileRef = useRef<HTMLInputElement>(null);

  function onPick(e: ChangeEvent<HTMLInputElement>) {
    const f = e.target.files?.[0];
    if (f) void upload(f);
    e.target.value = "";
  }

  return (
    <div className="settings-overlay" onClick={onClose}>
      <div
        className="settings project-panel"
        role="dialog"
        aria-modal="true"
        aria-labelledby="project-title"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="settings-head">
          <h2 id="project-title">{name}</h2>
          <button onClick={onClose} aria-label="Close" title="Close">✕</button>
        </div>

        <label className="field-label">Custom instructions</label>
        <textarea
          className="instructions"
          value={instructions}
          onChange={(e) => setInstructions(e.target.value)}
          onBlur={() => saveInstructions(instructions)}
          rows={6}
          placeholder="Guidelines the assistant follows for every chat in this project…"
        />

        <div className="knowledge-head">
          <label className="field-label">Knowledge</label>
          {capacity && (
            <div className="capacity">
              <div className="capacity-bar">
                <div className="capacity-fill" style={{ width: `${capacity.percent}%` }} />
              </div>
              <span className="capacity-text">
                {capacity.used_mb} / {capacity.max_mb} MB
              </span>
            </div>
          )}
        </div>

        <ul className="file-list">
          {files.map((f) => (
            <li key={f.name}>
              <span className="file-badge">{f.badge}</span>
              <span className="file-name" title={f.name}>
                {f.name}
              </span>
              <span className="file-size">{(f.size / 1024).toFixed(0)} KB</span>
            </li>
          ))}
          {files.length === 0 && <li className="file-empty">No files yet</li>}
        </ul>

        <div className="project-panel-actions">
          <input ref={fileRef} type="file" hidden onChange={onPick} />
          <button className="upload" onClick={() => fileRef.current?.click()} disabled={busy}>
            {busy ? "Uploading…" : "+ Add file"}
          </button>
          <button className="danger" onClick={onDelete}>
            Delete project
          </button>
        </div>
      </div>
    </div>
  );
}
