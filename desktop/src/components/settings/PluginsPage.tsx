import { useState } from "react";

import { Icon } from "../Icon";
import { DirCard, DirEmpty, DirToolbar } from "./DirCard";
import type { PluginControls } from "./types";
import { useDialogEscape } from "./useDialogEscape";
import { useRepoSync } from "./useRepoSync";

// Plugins + marketplace: installed plugins, a searchable marketplace grid, and the
// synced repository sources table.
export function PluginsPage({ p }: { p: PluginControls }) {
  const marketNames = new Set(p.market.map((m) => m.name));
  const [q, setQ] = useState("");
  const [category, setCategory] = useState("all");
  const [showAddMarket, setShowAddMarket] = useState(false);
  const categories = ["all", ...Array.from(new Set(p.market.map((m) => m.category))).sort()];
  const needle = q.trim().toLowerCase();
  const marketRows = p.market.filter(
    (m) =>
      (category === "all" || m.category === category) &&
      (!needle || (m.name + " " + m.description).toLowerCase().includes(needle)),
  );

  return (
    <>
      {p.err && <div className="settings-err">{p.err}</div>}

      {p.installed.length > 0 && (
        <>
          <h3 className="settings-subhead">Installed</h3>
          <div className="dir-grid">
            {p.installed.map((pl) => (
              <DirCard key={pl.name} icon="panel" title={pl.name}>
                <p className="dir-card-desc">{pl.description || "No description."}</p>
                <div className="dir-card-actions">
                  <label className="dir-toggle">
                    <input
                      type="checkbox"
                      aria-label={`Enable ${pl.name}`}
                      checked={p.enabled.includes(pl.name)}
                      onChange={() => p.onToggle(pl.name)}
                    />
                    Enabled
                  </label>
                  {marketNames.has(pl.name) && (
                    <button
                      className="dir-remove"
                      title="Uninstall"
                      aria-label={`Uninstall ${pl.name}`}
                      disabled={p.busy === pl.name}
                      onClick={() => p.onUninstall(pl.name)}
                    >
                      <Icon name="x" size={14} />
                    </button>
                  )}
                </div>
              </DirCard>
            ))}
          </div>
        </>
      )}

      <div className="settings-toolbar">
        <h3 className="settings-subhead" style={{ margin: 0 }}>Marketplace</h3>
        <span className="settings-toolbar-spacer" />
        <button className="settings-add" onClick={() => setShowAddMarket(true)}>
          <Icon name="plus" size={13} /> Add marketplace
        </button>
      </div>
      <DirToolbar q={q} onQ={setQ} placeholder="Search plugins…" />
      <div className="filter-chips" role="group" aria-label="Filter by category">
        {categories.map((c) => (
          <button
            key={c}
            className={`filter-chip ${category === c ? "active" : ""}`}
            onClick={() => setCategory(c)}
          >
            {c === "all" ? "All" : c}
          </button>
        ))}
      </div>
      <div className="dir-grid">
        {marketRows.map((m) => (
          <DirCard
            key={m.name}
            icon="panel"
            title={m.name}
            badges={
              <>
                <span className="badge-pill">{m.category}</span>
                {m.origin && m.origin !== "bundled" && (
                  <span className="badge-pill dir-origin" title={`From ${m.origin}`}>{m.origin}</span>
                )}
              </>
            }
          >
            <p className="dir-card-desc">{m.description}</p>
            <div className="dir-card-actions">
              {m.installed ? (
                <span className="plugin-installed">Installed ✓</span>
              ) : (
                <button
                  className="conn-install"
                  disabled={p.busy === m.name}
                  onClick={() => p.onInstall(m.name)}
                >
                  {p.busy === m.name ? "Installing…" : "Install"}
                </button>
              )}
            </div>
          </DirCard>
        ))}
        {marketRows.length === 0 && <DirEmpty>No matches.</DirEmpty>}
      </div>

      {p.sources.length > 0 && (
        <>
          <h3 className="settings-subhead">Repository sources</h3>
          <table className="stable">
            <thead>
              <tr>
                <th>Source</th>
                <th>URL</th>
                <th>Plugins</th>
                <th aria-label="Actions" />
              </tr>
            </thead>
            <tbody>
              {p.sources.map((s) => (
                <tr key={s.id}>
                  <td className="stable-name">{s.name}</td>
                  <td className="stable-sub">{s.url}{s.ref ? ` @ ${s.ref}` : ""}</td>
                  <td>{s.plugins}</td>
                  <td className="stable-actions">
                    <button
                      className="conn-del"
                      title="Remove source"
                      aria-label={`Remove ${s.name}`}
                      disabled={p.busy === s.id}
                      onClick={() => p.onRemoveSource(s.id)}
                    >
                      ✕
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}

      {showAddMarket && <AddMarketplaceModal p={p} onClose={() => setShowAddMarket(false)} />}
    </>
  );
}

// "Add marketplace" — sync a plugin marketplace from a git repository. Installing from
// here runs the repo's plugin CODE on this machine once you Install a specific plugin,
// so the flow leads with an explicit risk warning (contract: opt-in, not a silent add).
function AddMarketplaceModal({ p, onClose }: { p: PluginControls; onClose: () => void }) {
  const [step, setStep] = useState<"choose" | "repo">("choose");
  const [name, setName] = useState("");
  // Shared url/ref + busy/error + submit machine; the name is this variant's extra field.
  const { url, setUrl, ref, setRef, busy, err, submit } = useRepoSync(
    (u, r) => p.onAddSource(u, r, name.trim()),
    onClose,
  );
  useDialogEscape(onClose); // Escape closes only this dialog, not the whole Settings modal

  return (
    <div className="settings-overlay" onClick={onClose}>
      <div className="add-market-modal" role="dialog" aria-modal="true"
           aria-labelledby="add-market-title" onClick={(e) => e.stopPropagation()}
           onKeyDown={(e) => {
             // Keep Escape local to this dialog — don't bubble up and close Settings.
             if (e.key === "Escape") { e.stopPropagation(); onClose(); }
           }}>
        <header className="add-market-head">
          <h2 id="add-market-title">Add marketplace</h2>
          <button className="settings-close" aria-label="Close" title="Close" onClick={onClose}>✕</button>
        </header>

        {step === "choose" ? (
          <div className="add-market-choices">
            <button className="add-market-choice" onClick={() => setStep("repo")}>
              <span className="dir-card-icon"><Icon name="book" size={18} /></span>
              <span>
                <strong>Add from a repository</strong>
                <p>Sync a plugin marketplace from a GitHub repository or git URL.</p>
              </span>
            </button>
          </div>
        ) : (
          <div className="add-market-form">
            {!p.allowRemote ? (
              <p className="settings-err">
                Remote marketplaces are disabled on this install (MARKETPLACE_ALLOW_REMOTE=0).
              </p>
            ) : (
              <p className="add-market-warn">
                <strong>This runs third-party code.</strong> Installing a plugin from this
                repository executes its Python on this device. Only add sources you trust.
              </p>
            )}
            {err && <div className="settings-err">{err}</div>}
            <label className="field-label" htmlFor="mk-url">Repository URL</label>
            <input id="mk-url" placeholder="https://github.com/owner/repo.git"
                   value={url} onChange={(e) => setUrl(e.target.value)} />
            <label className="field-label" htmlFor="mk-ref">Branch or tag (optional)</label>
            <input id="mk-ref" placeholder="main" value={ref} onChange={(e) => setRef(e.target.value)} />
            <label className="field-label" htmlFor="mk-name">Display name (optional)</label>
            <input id="mk-name" placeholder={url ? url.split("/").pop() : "My marketplace"}
                   value={name} onChange={(e) => setName(e.target.value)} />
            <div className="drive-actions">
              <button className="btn-secondary" onClick={() => setStep("choose")}>Back</button>
              <button
                className="btn-primary"
                disabled={!url.trim() || busy || !p.allowRemote}
                onClick={() => void submit()}
              >
                {busy ? "Syncing…" : "Sync marketplace"}
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
