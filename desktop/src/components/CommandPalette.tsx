import { type KeyboardEvent, useMemo, useState } from "react";

import { filterByLabel } from "../state/commandFilter";

export interface Command {
  label: string;
  hint?: string;
  run: () => void;
}

export function CommandPalette({ commands, onClose }: { commands: Command[]; onClose: () => void }) {
  const [query, setQuery] = useState("");
  const [sel, setSel] = useState(0);
  const filtered = useMemo(() => filterByLabel(commands, query), [commands, query]);
  const active = Math.min(sel, Math.max(0, filtered.length - 1));

  function run(cmd?: Command) {
    if (cmd) {
      onClose();
      cmd.run();
    }
  }

  function onKey(e: KeyboardEvent<HTMLInputElement>) {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setSel((s) => Math.min(s + 1, filtered.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setSel((s) => Math.max(s - 1, 0));
    } else if (e.key === "Enter") {
      e.preventDefault();
      run(filtered[active]);
    } else if (e.key === "Escape") {
      onClose();
    }
  }

  return (
    <div className="palette-overlay" onClick={onClose}>
      <div className="palette" onClick={(e) => e.stopPropagation()}>
        <input
          autoFocus
          className="palette-input"
          placeholder="Type a command or search chats…"
          value={query}
          onChange={(e) => {
            setQuery(e.target.value);
            setSel(0);
          }}
          onKeyDown={onKey}
        />
        <ul className="palette-list">
          {filtered.slice(0, 50).map((c, i) => (
            <li
              key={i}
              className={i === active ? "active" : ""}
              onMouseEnter={() => setSel(i)}
              onClick={() => run(c)}
            >
              <span className="palette-label">{c.label}</span>
              {c.hint && <span className="palette-hint">{c.hint}</span>}
            </li>
          ))}
          {filtered.length === 0 && <li className="palette-empty">No matches</li>}
        </ul>
      </div>
    </div>
  );
}
