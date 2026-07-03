import { type KeyboardEvent, useMemo, useState } from "react";

import type { SkillSummary } from "../api/client";
import { applySlash, slashSuggestions } from "../state/slashCommands";

export function Composer({
  busy,
  onSend,
  onStop,
  skills = [],
}: {
  busy: boolean;
  onSend: (text: string) => void;
  onStop: () => void;
  skills?: SkillSummary[];
}) {
  const [text, setText] = useState("");
  const [sel, setSel] = useState(0);
  const suggestions = useMemo(() => slashSuggestions(skills, text), [skills, text]);
  const open = suggestions.length > 0;
  const active = Math.min(sel, Math.max(0, suggestions.length - 1));

  function submit() {
    if (!text.trim() || busy) return;
    onSend(text);
    setText("");
  }

  function accept(skill: SkillSummary) {
    setText(applySlash(skill));
    setSel(0);
  }

  function onKey(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (open) {
      if (e.key === "ArrowDown") {
        e.preventDefault();
        setSel((s) => Math.min(s + 1, suggestions.length - 1));
        return;
      }
      if (e.key === "ArrowUp") {
        e.preventDefault();
        setSel((s) => Math.max(s - 1, 0));
        return;
      }
      if (e.key === "Tab" || (e.key === "Enter" && !e.shiftKey)) {
        e.preventDefault();
        accept(suggestions[active]);
        return;
      }
      if (e.key === "Escape") {
        e.preventDefault();
        setText(""); // clear the in-progress slash to dismiss the menu
        return;
      }
    }
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      submit();
    }
  }

  return (
    <div className="composer">
      {open && (
        <ul className="slash-menu">
          {suggestions.map((s, i) => (
            <li
              key={s.name}
              className={i === active ? "active" : ""}
              onMouseEnter={() => setSel(i)}
              onClick={() => accept(s)}
            >
              <span className="slash-name">/{s.name}</span>
              {s.description && <span className="slash-desc">{s.description}</span>}
            </li>
          ))}
        </ul>
      )}
      <textarea
        value={text}
        onChange={(e) => {
          setText(e.target.value);
          setSel(0);
        }}
        onKeyDown={onKey}
        placeholder="Message Open Claude Desktop…  (type / for skills)"
        rows={1}
      />
      {busy ? (
        <button className="stop" onClick={onStop} title="Stop">
          ■
        </button>
      ) : (
        <button className="send" onClick={submit} disabled={!text.trim()} title="Send">
          ↑
        </button>
      )}
    </div>
  );
}
