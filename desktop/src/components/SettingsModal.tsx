import { useState } from "react";

import type { ThemePref } from "../state/theme";
import { Icon } from "./Icon";
import { CapabilitiesPage } from "./settings/CapabilitiesPage";
import { ConnectorsPage } from "./settings/ConnectorsPage";
import { DeveloperPage } from "./settings/DeveloperPage";
import { ExtensionsPage } from "./settings/ExtensionsPage";
import { GeneralPage } from "./settings/GeneralPage";
import { PluginsPage } from "./settings/PluginsPage";
import { ProvidersPage } from "./settings/ProvidersPage";
import { SkillsPage } from "./settings/SkillsPage";
import {
  AccountPage,
  BillingPage,
  ChromePage,
  ClaudeCodePage,
  CoworkPage,
  DesktopGeneralPage,
  PrivacyPage,
  UsagePage,
} from "./settings/StaticPages";
import {
  type ConnectorControls,
  type PluginControls,
  SETTINGS_NAV,
  type SettingsPage,
  type SkillControls,
} from "./settings/types";

// Re-export the page/control types so existing importers (App) keep their import path.
export type { ConnectorControls, PluginControls, SettingsPage, SkillControls };

// The Settings window: searchable grouped left-nav (Settings / Desktop app /
// Customize) + a page pane, mirroring Claude Desktop. Pages whose backend exists are
// live; the rest render faithfully with disabled controls. The shell only handles
// nav + dispatch; each page lives in components/settings/.
export function SettingsModal({
  page,
  onPage,
  onClose,
  active,
  onPick,
  skills,
  conn,
  plug,
  theme,
}: {
  page: SettingsPage;
  onPage: (p: SettingsPage) => void;
  onClose: () => void;
  active: { provider: string; model: string };
  onPick: (provider: string, model: string) => void;
  skills: SkillControls;
  conn: ConnectorControls;
  plug: PluginControls;
  theme: { pref: ThemePref; set: (p: ThemePref) => void };
}) {
  const [q, setQ] = useState("");
  const needle = q.trim().toLowerCase();
  const groups = SETTINGS_NAV.map((g) => ({
    ...g,
    items: g.items.filter(
      (it) =>
        !needle ||
        it.label.toLowerCase().includes(needle) ||
        (it.keywords ?? "").toLowerCase().includes(needle),
    ),
  })).filter((g) => g.items.length > 0);

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
          <div className="settings-nav-search">
            <Icon name="search" size={13} />
            <input
              placeholder="Search"
              aria-label="Search settings"
              value={q}
              onChange={(e) => setQ(e.target.value)}
            />
          </div>
          {groups.map((g) => (
            <div key={g.group} className="settings-nav-group">
              <div className="settings-nav-label">{g.group}</div>
              {g.items.map((it) => (
                <button
                  key={it.id}
                  className={`settings-nav-item ${page === it.id ? "active" : ""}`}
                  onClick={() => onPage(it.id)}
                >
                  <Icon name={it.icon} size={14} />
                  {it.label}
                </button>
              ))}
            </div>
          ))}
          {groups.length === 0 && <div className="settings-nav-label">No matches</div>}
        </aside>

        <section className="settings-page">
          <header className="settings-page-head">
            <h2 id="settings-title">{title}</h2>
            <button className="settings-close" aria-label="Close" title="Close" onClick={onClose}>
              ✕
            </button>
          </header>
          <div className="settings-page-body">
            {page === "general" && <GeneralPage theme={theme} />}
            {page === "providers" && <ProvidersPage active={active} onPick={onPick} />}
            {page === "account" && <AccountPage />}
            {page === "privacy" && <PrivacyPage />}
            {page === "billing" && <BillingPage />}
            {page === "usage" && <UsagePage />}
            {page === "capabilities" && <CapabilitiesPage />}
            {page === "claude-code" && <ClaudeCodePage />}
            {page === "cowork" && <CoworkPage />}
            {page === "chrome" && <ChromePage />}
            {page === "desktop-general" && <DesktopGeneralPage />}
            {page === "extensions" && <ExtensionsPage c={conn} />}
            {page === "developer" && <DeveloperPage c={conn} />}
            {page === "skills" && <SkillsPage c={skills} />}
            {page === "connectors" && <ConnectorsPage c={conn} />}
            {page === "plugins" && <PluginsPage p={plug} />}
          </div>
        </section>
      </div>
    </div>
  );
}
