import { SHORTCUTS } from "../state/shortcuts";

export function ShortcutsHelp({ onClose }: { onClose: () => void }) {
  return (
    <div className="settings-overlay" onClick={onClose}>
      <div className="shortcuts" onClick={(e) => e.stopPropagation()}>
        <div className="settings-head">
          <h2>Keyboard shortcuts</h2>
          <button onClick={onClose}>✕</button>
        </div>
        <ul className="shortcut-list">
          {SHORTCUTS.map((s) => (
            <li key={s.keys}>
              <kbd className="shortcut-keys">{s.keys}</kbd>
              <span className="shortcut-action">{s.action}</span>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}
