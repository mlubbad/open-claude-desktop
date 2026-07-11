// Shared building blocks for Settings pages: section headings, label/control rows,
// toggle switches, and segmented pickers — matching Claude Desktop's settings look.
//
// The `locked` variant is the contract for anything whose backend doesn't exist in
// this build: the control renders faithfully but disabled, with a tooltip saying so,
// instead of being hidden (the page layout stays true to the reference).

import type { ReactNode } from "react";

export const LOCKED_NOTE = "Not available in this build yet";

export function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="set-section">
      <h3 className="set-section-title">{title}</h3>
      {children}
    </section>
  );
}

export function Row({
  label,
  desc,
  badge,
  locked,
  children,
  stacked,
}: {
  label: string;
  desc?: ReactNode;
  badge?: string;
  locked?: boolean;
  children?: ReactNode;
  stacked?: boolean; // control renders under the text instead of to the right
}) {
  return (
    <div className={`set-row ${stacked ? "stacked" : ""} ${locked ? "locked" : ""}`}
         title={locked ? LOCKED_NOTE : undefined}>
      <div className="set-row-text">
        <div className="set-row-label">
          {label}
          {badge && <span className="set-badge">{badge}</span>}
        </div>
        {desc && <div className="set-row-desc">{desc}</div>}
      </div>
      {children && <div className="set-row-control">{children}</div>}
    </div>
  );
}

export function Toggle({
  on,
  onChange,
  disabled,
  label,
}: {
  on: boolean;
  onChange?: (v: boolean) => void;
  disabled?: boolean;
  label: string;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={on}
      aria-label={label}
      className={`toggle ${on ? "on" : ""}`}
      disabled={disabled}
      title={disabled ? LOCKED_NOTE : undefined}
      onClick={() => onChange?.(!on)}
    >
      <span className="toggle-knob" />
    </button>
  );
}

export function Segmented<T extends string>({
  options,
  value,
  onChange,
  disabled,
  label,
}: {
  options: { value: T; label: ReactNode; title?: string }[];
  value: T;
  onChange?: (v: T) => void;
  disabled?: boolean;
  label: string;
}) {
  return (
    <div className={`segmented ${disabled ? "disabled" : ""}`} role="radiogroup" aria-label={label}>
      {options.map((o) => (
        <button
          key={o.value}
          type="button"
          role="radio"
          aria-checked={value === o.value}
          className={`segment ${value === o.value ? "active" : ""}`}
          disabled={disabled}
          title={o.title ?? (disabled ? LOCKED_NOTE : undefined)}
          onClick={() => onChange?.(o.value)}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

// A right-aligned <select> that reads as Claude Desktop's inline dropdowns.
export function InlineSelect({
  value,
  onChange,
  options,
  disabled,
  label,
}: {
  value: string;
  onChange?: (v: string) => void;
  options: { value: string; label: string }[];
  disabled?: boolean;
  label: string;
}) {
  return (
    <select
      className="set-select"
      value={value}
      aria-label={label}
      disabled={disabled}
      title={disabled ? LOCKED_NOTE : undefined}
      onChange={(e) => onChange?.(e.target.value)}
    >
      {options.map((o) => (
        <option key={o.value} value={o.value}>{o.label}</option>
      ))}
    </select>
  );
}

// Disabled action button for reference-faithful rows without a backend.
export function LockedButton({ children }: { children: ReactNode }) {
  return (
    <button type="button" className="set-btn" disabled title={LOCKED_NOTE}>
      {children}
    </button>
  );
}
