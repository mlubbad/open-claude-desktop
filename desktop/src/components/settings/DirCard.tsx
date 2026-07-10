import type { ReactNode } from "react";

import { Icon, type IconName } from "../Icon";

// The search box atop each Directory grid page (Skills / Connectors / Plugins).
export function DirToolbar({ q, onQ, placeholder }: { q: string; onQ: (v: string) => void; placeholder: string }) {
  return (
    <div className="dir-search">
      <Icon name="search" size={14} />
      <input value={q} onChange={(e) => onQ(e.target.value)} placeholder={placeholder} aria-label={placeholder} />
    </div>
  );
}

// A single directory card: the outer frame + head (icon, title, badges) is identical
// across Skills / Connectors / Plugins; each page passes its own body (description,
// error, actions) as children. `key` goes on the element at the call site as usual.
export function DirCard({
  icon,
  title,
  badges,
  className,
  children,
}: {
  icon: IconName;
  title: ReactNode;
  badges?: ReactNode;
  className?: string;
  children?: ReactNode;
}) {
  return (
    <div className={`dir-card${className ? ` ${className}` : ""}`}>
      <div className="dir-card-head">
        <span className="dir-card-icon"><Icon name={icon} size={16} /></span>
        <span className="dir-card-title">{title}</span>
        {badges}
      </div>
      {children}
    </div>
  );
}

// The empty-state row shown under a directory grid when there are no (matching) cards.
export function DirEmpty({ children }: { children: ReactNode }) {
  return <div className="dir-empty">{children}</div>;
}
