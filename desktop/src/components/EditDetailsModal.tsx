import { useEffect, useRef, useState } from "react";

import { Icon } from "./Icon";

// "Edit details" modal (Claude Desktop): edit a project's Name + Description.
export function EditDetailsModal({
  initialName,
  initialDescription,
  onSave,
  onClose,
}: {
  initialName: string;
  initialDescription: string;
  onSave: (name: string, description: string) => void;
  onClose: () => void;
}) {
  const [name, setName] = useState(initialName);
  const [description, setDescription] = useState(initialDescription);
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
    onSave(name.trim(), description.trim());
  }

  return (
    <div className="modal-overlay" onMouseDown={onClose}>
      <div className="modal" role="dialog" aria-modal="true" aria-label="Edit details"
           onMouseDown={(e) => e.stopPropagation()}>
        <div className="modal-head">
          <h2 className="modal-title">Edit details</h2>
          <button className="modal-close" aria-label="Close" onClick={onClose}><Icon name="x" size={16} /></button>
        </div>
        <label className="modal-label" htmlFor="ed-name">Name</label>
        <input id="ed-name" ref={nameRef} className="modal-input" value={name}
               onChange={(e) => setName(e.target.value)}
               onKeyDown={(e) => { if (e.key === "Enter") submit(); }} />
        <label className="modal-label" htmlFor="ed-desc">Description</label>
        <textarea id="ed-desc" className="modal-input modal-textarea" value={description}
                  onChange={(e) => setDescription(e.target.value)} />
        <div className="modal-actions">
          <button className="btn-secondary" onClick={onClose}>Cancel</button>
          <button className="btn-primary" disabled={!name.trim()} onClick={submit}>Save</button>
        </div>
      </div>
    </div>
  );
}
