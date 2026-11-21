import type { TranscriptState } from "../state/transcript";

export function ApprovalPrompt({
  pending,
  onDecide,
}: {
  pending: NonNullable<TranscriptState["pendingApproval"]>;
  onDecide: (decision: "approve" | "decline") => void;
}) {
  // Plan approval (exit_plan_mode) gets a purpose-built prompt: the "input" IS the plan.
  const isPlan = pending.name === "exit_plan_mode";

  return (
    <div className={`approval ${isPlan ? "approval-plan" : ""}`}>
      <div className="approval-head">
        {isPlan ? (
          <>Ready to go? Review the plan before the agent makes any changes:</>
        ) : (
          <>
            Allow <code>{pending.name}</code> to run?
          </>
        )}
      </div>
      {pending.input && <pre className="approval-input">{pending.input}</pre>}
      <div className="approval-actions">
        <button className="decline" onClick={() => onDecide("decline")}>
          {isPlan ? "Keep planning" : "Decline"}
        </button>
        <button className="approve" onClick={() => onDecide("approve")}>
          {isPlan ? "Approve & run" : "Approve"}
        </button>
      </div>
    </div>
  );
}
