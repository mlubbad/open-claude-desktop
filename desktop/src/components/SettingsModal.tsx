import { CapabilitiesPage } from "./settings/CapabilitiesPage";
import { ConnectorsPage } from "./settings/ConnectorsPage";
import { GeneralPage } from "./settings/GeneralPage";
import { PluginsPage } from "./settings/PluginsPage";
import { ProvidersPage } from "./settings/ProvidersPage";
import { SkillsPage } from "./settings/SkillsPage";
import {
  type ConnectorControls,
  type PluginControls,
  SETTINGS_NAV,
  type SettingsPage,
  type SkillControls,
} from "./settings/types";

// Re-export the page/control types so existing importers (App) keep their import path.
export type { ConnectorControls, PluginControls, SettingsPage, SkillControls };

// The unified Settings modal: grouped left-nav + a page pane, hosting every management
// surface (profile, BYOK providers, capabilities, skills, MCP connectors, plugins/
// marketplace). The shell only handles nav + page dispatch; each page lives in
// components/settings/. Every callback passes through unchanged from the hooks.
export function SettingsModal({
  page,
  onPage,
  onClose,
  active,
  onPick,
  skills,
  conn,
  plug,
}: {
  page: SettingsPage;
  onPage: (p: SettingsPage) => void;
  onClose: () => void;
  active: { provider: string; model: string };
  onPick: (provider: string, model: string) => void;
  skills: SkillControls;
  conn: ConnectorControls;
  plug: PluginControls;
}) {
  const title = SETTINGS_NAV.flatMap((g) => g.items).find((i) => i.id === page)?.label ?? "Settings";

  return (
    <div className="settings-overlay" onClick={onClose}>
      <div
        className="settings-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="settings-title"
        onClick={(e) => e.stopPropagation()}
      >
        <aside className="settings-nav">
          {SETTINGS_NAV.map((g) => (
            <div key={g.group} className="settings-nav-group">
              <div className="settings-nav-label">{g.group}</div>
              {g.items.map((it) => (
                <button
                  key={it.id}
                  className={`settings-nav-item ${page === it.id ? "active" : ""}`}
                  onClick={() => onPage(it.id)}
                >
                  {it.label}
                </button>
              ))}
            </div>
          ))}
        </aside>

        <section className="settings-page">
          <header className="settings-page-head">
            <h2 id="settings-title">{title}</h2>
            <button className="settings-close" aria-label="Close" title="Close" onClick={onClose}>
              ✕
            </button>
          </header>
          <div className="settings-page-body">
            {page === "general" && <GeneralPage />}
            {page === "providers" && <ProvidersPage active={active} onPick={onPick} />}
            {page === "capabilities" && <CapabilitiesPage />}
            {page === "skills" && <SkillsPage c={skills} />}
            {page === "connectors" && <ConnectorsPage c={conn} />}
            {page === "plugins" && <PluginsPage p={plug} />}
          </div>
        </section>
      </div>
    </div>
  );
}
