import type { PlanItem } from "../api/events";

// The task_plan tool's current plan, rendered from the latest plan_update event (each
// event carries the FULL plan, so this always shows the authoritative current state).
export function PlanCard({ items }: { items: PlanItem[] }) {
  const mark = (status: string) =>
    status === "completed" ? "✓" : status === "in_progress" ? "▸" : "○";
  return (
    <ul className="plan-card">
      {items.map((it) => (
        <li key={it.id} data-status={it.status}>
          <span className="plan-card-mark" aria-hidden="true">{mark(it.status)}</span>
          <span className="plan-card-subject">{it.subject}</span>
        </li>
      ))}
    </ul>
  );
}
