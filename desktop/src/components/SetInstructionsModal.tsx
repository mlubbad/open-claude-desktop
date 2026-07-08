import { useEffect, useRef, useState } from "react";

import { Icon } from "./Icon";

// "Set project instructions" modal (Claude Desktop): a textarea that seeds every chat in
// the project. Works alongside the user's profile instructions and the chat style.
export function SetInstructionsModal({
  projectName,
  initial,
  onSave,
  onClose,
}: {
  projectName: string;
  initial: string;
  onSave: (text: string) => void;
  onClose: () => void;
}) {
  const [text, setText] = useState(initial);
  const ref = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    ref.current?.focus();
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") {
        e.stopPropagation();
        onClose();
      }
    }
    document.addEventListener("keydown", onKey, true);
    return () => document.removeEventListener("keydown", onKey, true);
  }, [onClose]);

  return (
    <div className="modal-overlay" onMouseDown={onClose}>
      <div className="modal modal-wide" role="dialog" aria-modal="true" aria-label="Set project instructions"
           onMouseDown={(e) => e.stopPropagation()}>
        <div className="modal-head">
          <h2 className="modal-title">Set project instructions</h2>
          <button className="modal-close" aria-label="Close" onClick={onClose}><Icon name="x" size={16} /></button>
        </div>
        <p className="modal-sub">
          These instructions are added to every chat in <strong>{projectName}</strong> —
          describe how the assistant should work here, what to prioritize, and any context it
          should always keep in mind. They apply on top of your global profile settings.
        </p>
        <textarea
          ref={ref}
          className="modal-input modal-textarea tall"
          placeholder="e.g. Always answer with data from this project's files. Prefer concise, cited responses."
          value={text}
          onChange={(e) => setText(e.target.value)}
        />
        <div className="modal-actions">
          <button className="btn-secondary" onClick={onClose}>Cancel</button>
          <button className="btn-primary" onClick={() => onSave(text)}>Save instructions</button>
        </div>
      </div>
    </div>
  );
}
