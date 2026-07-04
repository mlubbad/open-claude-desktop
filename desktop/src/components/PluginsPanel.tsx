import type { MarketplacePlugin, PluginSummary } from "../api/client";

// Manage plugins: toggle installed plugins on for the session (fed into each turn as
// enabled_plugins), and browse the bundled marketplace to install / uninstall more.
export function PluginsPanel({
  installed,
  market,
  enabled,
  err,
  busy,
  onToggle,
  onInstall,
  onUninstall,
  onClose,
}: {
  installed: PluginSummary[];
  market: MarketplacePlugin[];
  enabled: string[];
  err: string | null;
  busy: string | null;
  onToggle: (name: string) => void;
  onInstall: (name: string) => void;
  onUninstall: (name: string) => void;
  onClose: () => void;
}) {
  // Only marketplace-sourced plugins can be uninstalled; built-ins stay put.
  const marketNames = new Set(market.map((m) => m.name));

  return (
    <div className="settings-overlay" onClick={onClose}>
      <div className="settings" onClick={(e) => e.stopPropagation()}>
        <div className="settings-head">
          <h2>Plugins</h2>
          <button onClick={onClose}>✕</button>
        </div>
        {err && <div className="settings-err">{err}</div>}

        <h3 className="plugins-section">Installed</h3>
        {installed.length === 0 && <div className="code-empty">No plugins installed yet.</div>}
        <ul className="conn-list">
          {installed.map((p) => (
            <li key={p.name}>
              <label className="conn-enable">
                <input
                  type="checkbox"
                  checked={enabled.includes(p.name)}
                  onChange={() => onToggle(p.name)}
                />
              </label>
              <span className="conn-meta">
                <span className="conn-name">{p.name}</span>
                <span className="conn-sub">{p.description}</span>
              </span>
              {marketNames.has(p.name) && (
                <button
                  className="conn-del"
                  title="Uninstall"
                  disabled={busy === p.name}
                  onClick={() => onUninstall(p.name)}
                >
                  🗑
                </button>
              )}
            </li>
          ))}
        </ul>

        <h3 className="plugins-section">Marketplace</h3>
        <p className="plugins-note">Vetted, offline plugins bundled with the app.</p>
        <ul className="conn-list">
          {market.map((m) => (
            <li key={m.name}>
              <span className="conn-meta">
                <span className="conn-name">
                  {m.name} <span className="conn-badge">{m.category}</span>
                </span>
                <span className="conn-sub">{m.description}</span>
              </span>
              {m.installed ? (
                <span className="plugin-installed">Installed ✓</span>
              ) : (
                <button
                  className="conn-install"
                  disabled={busy === m.name}
                  onClick={() => onInstall(m.name)}
                >
                  {busy === m.name ? "Installing…" : "Install"}
                </button>
              )}
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}
