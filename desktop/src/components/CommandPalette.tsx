import { type KeyboardEvent, useEffect, useMemo, useState } from "react";

import { filterByLabel } from "../state/commandFilter";

export interface Command {
  label: string;
  hint?: string;
  sub?: string; // secondary line (e.g. a search snippet)
  run: () => void;
}

export function CommandPalette({
  commands,
  onClose,
  search,
}: {
  commands: Command[];
  onClose: () => void;
  // Optional async content search (e.g. full-text over chat bodies). Results are
  // appended under an "In chats" section.
  search?: (query: string) => Promise<Command[]>;
}) {
  const [query, setQuery] = useState("");
  const [sel, setSel] = useState(0);
  const [remote, setRemote] = useState<Command[]>([]);
  const local = useMemo(() => filterByLabel(commands, query), [commands, query]);

  // Debounced content search — only for queries of 2+ chars, cancelled on change.
  useEffect(() => {
    const q = query.trim();
    if (!search || q.length < 2) {
      setRemote([]);
      return;
    }
    let cancelled = false;
    const t = setTimeout(() => {
      search(q)
        .then((r) => !cancelled && setRemote(r))
        .catch(() => !cancelled && setRemote([]));
    }, 180);
    return () => {
      cancelled = true;
      clearTimeout(t);
    };
  }, [query, search]);

  const all = useMemo(() => [...local, ...remote], [local, remote]);
  const active = Math.min(sel, Math.max(0, all.length - 1));

  function run(cmd?: Command) {
    if (cmd) {
      onClose();
      cmd.run();
    }
  }

  function onKey(e: KeyboardEvent<HTMLInputElement>) {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setSel((s) => Math.min(s + 1, all.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setSel((s) => Math.max(s - 1, 0));
    } else if (e.key === "Enter") {
      e.preventDefault();
      run(all[active]);
    } else if (e.key === "Escape") {
      onClose();
    }
  }

  function item(c: Command, i: number) {
    return (
      <li
        key={i}
        id={`palette-opt-${i}`}
        role="option"
        aria-selected={i === active}
        className={i === active ? "active" : ""}
        onMouseEnter={() => setSel(i)}
        onClick={() => run(c)}
      >
        <span className="palette-row">
          <span className="palette-label">{c.label}</span>
          {c.hint && <span className="palette-hint">{c.hint}</span>}
        </span>
        {c.sub && <span className="palette-sub">{c.sub}</span>}
      </li>
    );
  }

  return (
    <div className="palette-overlay" onClick={onClose}>
      <div
        className="palette"
        role="dialog"
        aria-modal="true"
        aria-label="Command palette"
        onClick={(e) => e.stopPropagation()}
      >
        <input
          autoFocus
          className="palette-input"
          placeholder="Type a command or search chats…"
          role="combobox"
          aria-expanded={all.length > 0}
          aria-controls="palette-listbox"
          aria-activedescendant={all.length > 0 ? `palette-opt-${active}` : undefined}
          value={query}
          onChange={(e) => {
            setQuery(e.target.value);
            setSel(0);
          }}
          onKeyDown={onKey}
        />
        <ul className="palette-list" id="palette-listbox" role="listbox" aria-label="Commands">
          {local.slice(0, 50).map((c, i) => item(c, i))}
          {remote.length > 0 && <li className="palette-section" role="presentation">In chats</li>}
          {remote.slice(0, 50).map((c, i) => item(c, local.length + i))}
          {all.length === 0 && <li className="palette-empty">No matches</li>}
        </ul>
      </div>
    </div>
  );
}
