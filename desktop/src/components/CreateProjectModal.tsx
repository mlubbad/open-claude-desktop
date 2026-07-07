import { useEffect, useRef, useState } from "react";

import { Icon } from "./Icon";

// The "Create a project" modal (contract §7.1): a name field + a goal textarea,
// dimmed backdrop, ✕, and Cancel / Create-project footer. Create is disabled until
// the project has a name. The goal seeds the project's instructions.
export function CreateProjectModal({
  onCreate,
  onClose,
}: {
  onCreate: (name: string, goal: string) => void;
  onClose: () => void;
}) {
  const [name, setName] = useState("");
  const [goal, setGoal] = useState("");
  const nameRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    nameRef.current?.focus();
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") {
        e.stopPropagation();
        onClose();
      }
    }
    document.addEventListener("keydown", onKey, true);
    return () => document.removeEventListener("keydown", onKey, true);
  }, [onClose]);

  function submit() {
    if (!name.trim()) return;
    onCreate(name.trim(), goal.trim());
  }

  return (
    <div className="modal-overlay" onMouseDown={onClose}>
      <div className="modal" role="dialog" aria-modal="true" aria-label="Create a project"
           onMouseDown={(e) => e.stopPropagation()}>
        <div className="modal-head">
          <h2 className="modal-title">Create a project</h2>
          <button className="modal-close" aria-label="Close" onClick={onClose}><Icon name="x" size={16} /></button>
        </div>
        <label className="modal-label" htmlFor="cp-name">What are you working on?</label>
        <input id="cp-name" ref={nameRef} className="modal-input" placeholder="Name your project"
               value={name} onChange={(e) => setName(e.target.value)}
               onKeyDown={(e) => { if (e.key === "Enter") submit(); }} />
        <label className="modal-label" htmlFor="cp-goal">What are you trying to achieve?</label>
        <textarea id="cp-goal" className="modal-input modal-textarea"
                  placeholder="Describe your project, goals, subject, etc…"
                  value={goal} onChange={(e) => setGoal(e.target.value)} />
        <div className="modal-actions">
          <button className="btn-secondary" onClick={onClose}>Cancel</button>
          <button className="btn-primary" disabled={!name.trim()} onClick={submit}>Create project</button>
        </div>
      </div>
    </div>
  );
}
