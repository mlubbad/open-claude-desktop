import type { Usage } from "../api/events";

// Compact context-fill + cost indicator for the most recent turn. Sits in the topbar.
export function UsageMeter({ usage }: { usage: Usage }) {
  const pct = Math.min(100, Math.max(0, usage.context_pct));
  const warn = pct >= 80;
  const k = (n: number) => (n >= 1000 ? `${(n / 1000).toFixed(1)}k` : `${n}`);
  return (
    <div className="usage-meter" title={`${usage.context_tokens} / ${usage.context_limit} context tokens`}>
      <div className="usage-bar">
        <div className={`usage-fill ${warn ? "warn" : ""}`} style={{ width: `${pct}%` }} />
      </div>
      <span className="usage-text">
        {k(usage.context_tokens)}/{k(usage.context_limit)} · {pct}%
        {usage.cost_usd != null && <> · ${usage.cost_usd.toFixed(usage.cost_usd < 0.01 ? 4 : 2)}</>}
      </span>
    </div>
  );
}
