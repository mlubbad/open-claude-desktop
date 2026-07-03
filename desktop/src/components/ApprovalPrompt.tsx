import type { TranscriptState } from "../state/transcript";

export function ApprovalPrompt({
  pending,
  onDecide,
}: {
  pending: NonNullable<TranscriptState["pendingApproval"]>;
  onDecide: (decision: "approve" | "decline") => void;
}) {
  return (
    <div className="approval">
      <div className="approval-head">
        Allow <code>{pending.name}</code> to run?
      </div>
      {pending.input && <pre className="approval-input">{pending.input}</pre>}
      <div className="approval-actions">
        <button className="decline" onClick={() => onDecide("decline")}>
          Decline
        </button>
        <button className="approve" onClick={() => onDecide("approve")}>
          Approve
        </button>
      </div>
    </div>
  );
}
