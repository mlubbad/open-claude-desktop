import { useEffect, useState } from "react";

import { Icon } from "./Icon";

const ISSUE_TYPES = [
  "Not helpful",
  "Incorrect or misleading",
  "Didn't follow instructions",
  "Unsafe or harmful",
  "Other",
];

// The "Give negative feedback" modal (contract §7.2): an issue-type select + a
// details textarea + a privacy note, Cancel / Submit. In our BYOK build nothing is
// sent to any vendor — feedback is recorded locally via onSubmit (the note reflects
// that, unlike the reference's "send to Anthropic" wording).
export function FeedbackModal({
  onSubmit,
  onClose,
}: {
  onSubmit: (issueType: string, details: string) => void;
  onClose: () => void;
}) {
  const [issue, setIssue] = useState("");
  const [details, setDetails] = useState("");

  useEffect(() => {
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
      <div className="modal" role="dialog" aria-modal="true" aria-label="Give negative feedback"
           onMouseDown={(e) => e.stopPropagation()}>
        <div className="modal-head">
          <h2 className="modal-title">Give negative feedback</h2>
          <button className="modal-close" aria-label="Close" onClick={onClose}><Icon name="x" size={16} /></button>
        </div>
        <label className="modal-label" htmlFor="fb-type">What type of issue do you wish to report? (optional)</label>
        <select id="fb-type" className="modal-input" value={issue} onChange={(e) => setIssue(e.target.value)}>
          <option value="">Select…</option>
          {ISSUE_TYPES.map((t) => (
            <option key={t} value={t}>{t}</option>
          ))}
        </select>
        <label className="modal-label" htmlFor="fb-details">Please provide details: (optional)</label>
        <textarea id="fb-details" className="modal-input modal-textarea"
                  placeholder="What was unsatisfying about this response?"
                  value={details} onChange={(e) => setDetails(e.target.value)} />
        <p className="modal-fine">
          This feedback is stored locally on your device to help you track responses — nothing is sent to
          any provider.
        </p>
        <div className="modal-actions">
          <button className="btn-secondary" onClick={onClose}>Cancel</button>
          <button className="btn-primary" onClick={() => onSubmit(issue, details)}>Submit</button>
        </div>
      </div>
    </div>
  );
}
