import { useEffect, useState } from "react";

import {
  type AddMcpBody,
  type MarketplacePlugin,
  type McpServer,
  type PluginSummary,
  type ProviderInfo,
  providers,
  settings as settingsApi,
  type SkillSummary,
  type UserProfile,
} from "../api/client";

export type SettingsPage =
  | "general"
  | "providers"
  | "capabilities"
  | "skills"
  | "connectors"
  | "plugins";

const NAV: { group: string; items: { id: SettingsPage; label: string }[] }[] = [
  {
    group: "Settings",
    items: [
      { id: "general", label: "General" },
      { id: "providers", label: "Models & keys" },
      { id: "capabilities", label: "Capabilities" },
    ],
  },
  {
    group: "Customize",
    items: [
      { id: "skills", label: "Skills" },
      { id: "connectors", label: "Connectors" },
      { id: "plugins", label: "Plugins" },
    ],
  },
];

export interface ConnectorControls {
  servers: McpServer[];
  enabled: string[];
  err: string | null;
  onAdd: (body: AddMcpBody) => void;
  onAddDemo: () => void;
  onInstall: (file: File) => void;
  onAddOAuth: (name: string, url: string) => void;
  onAuthorize: (sid: string) => void;
  onRemove: (sid: string) => void;
  onToggle: (sid: string) => void;
}

export interface PluginControls {
  installed: PluginSummary[];
  market: MarketplacePlugin[];
  enabled: string[];
  err: string | null;
  busy: string | null;
  onToggle: (name: string) => void;
  onInstall: (name: string) => void;
  onUninstall: (name: string) => void;
}

// The unified Settings modal: grouped left-nav + a page pane, hosting every
// management surface (profile, BYOK providers, web search, skills, MCP connectors,
// plugins/marketplace). Every callback passes through unchanged from the hooks.
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
  skills: SkillSummary[];
  conn: ConnectorControls;
  plug: PluginControls;
}) {
  const title = NAV.flatMap((g) => g.items).find((i) => i.id === page)?.label ?? "Settings";

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
          {NAV.map((g) => (
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
            {page === "skills" && <SkillsPage skills={skills} />}
            {page === "connectors" && <ConnectorsPage c={conn} />}
            {page === "plugins" && <PluginsPage p={plug} />}
          </div>
        </section>
      </div>
    </div>
  );
}

/* ---------------- General: user profile ---------------- */

function GeneralPage() {
  const [profile, setProfile] = useState<UserProfile>({});
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    settingsApi
      .get()
      .then((s) => setProfile(s.profile ?? {}))
      .catch(() => {});
  }, []);

  function save() {
    void settingsApi.save({ profile }).catch((e) => setErr(String(e)));
  }
  function setField(k: keyof UserProfile, v: string) {
    setProfile((p) => ({ ...p, [k]: v }));
  }

  return (
    <>
      {err && <div className="settings-err">{err}</div>}
      <p className="settings-hint">Personalizes every chat — injected into the system prompt.</p>
      <div className="profile-form">
        <label className="field-label" htmlFor="pf-name">What should the assistant call you?</label>
        <input id="pf-name" value={profile.call_me ?? ""}
               onChange={(e) => setField("call_me", e.target.value)} onBlur={save} />
        <label className="field-label" htmlFor="pf-role">Your role or work (optional)</label>
        <input id="pf-role" value={profile.role ?? ""}
               onChange={(e) => setField("role", e.target.value)} onBlur={save} />
        <label className="field-label" htmlFor="pf-prefs">Response preferences</label>
        <textarea id="pf-prefs" rows={3} placeholder="Tone, length, format…"
                  value={profile.preferences ?? ""}
                  onChange={(e) => setField("preferences", e.target.value)} onBlur={save} />
      </div>
    </>
  );
}

/* ---------------- Models & keys: BYOK providers ---------------- */

function ProvidersPage({
  active,
  onPick,
}: {
  active: { provider: string; model: string };
  onPick: (provider: string, model: string) => void;
}) {
  const [list, setList] = useState<ProviderInfo[]>([]);
  const [keyDraft, setKeyDraft] = useState<Record<string, string>>({});
  const [err, setErr] = useState<string | null>(null);
  const [probing, setProbing] = useState<string | null>(null);
  const [probe, setProbe] = useState<Record<string, { ok: boolean; detail: string }>>({});

  async function refresh() {
    try {
      setList(await providers.list());
    } catch (e) {
      setErr(String(e));
    }
  }
  useEffect(() => {
    void refresh();
  }, []);

  async function testProvider(id: string) {
    setProbing(id);
    try {
      const r = await providers.test(id);
      setProbe((p) => ({ ...p, [id]: { ok: r.ok, detail: r.detail } }));
    } catch (e) {
      setProbe((p) => ({ ...p, [id]: { ok: false, detail: String(e) } }));
    } finally {
      setProbing(null);
    }
  }

  async function saveKey(id: string) {
    try {
      await providers.setKey(id, keyDraft[id] ?? "");
      setKeyDraft((d) => ({ ...d, [id]: "" }));
      await refresh();
    } catch (e) {
      setErr(String(e));
    }
  }

  return (
    <>
      {err && <div className="settings-err">{err}</div>}
      <p className="settings-hint">
        Bring your own key — pick any OpenAI-compatible provider. Keys are stored in the OS
        keychain and never read back.
      </p>
      <ul className="provider-list">
        {list.map((p) => (
          <li key={p.id} className={p.id === active.provider ? "active" : ""}>
            <div className="provider-row">
              <span className="provider-label">
                {p.label} {p.is_local && <em>(local)</em>}
              </span>
              <span className="provider-row-right">
                <button
                  className="provider-test"
                  disabled={probing === p.id || (p.requires_key && !p.has_key)}
                  onClick={() => void testProvider(p.id)}
                  title="Test the connection"
                >
                  {probing === p.id ? "Testing…" : "Test"}
                </button>
                <span className={`key-badge ${p.has_key ? "ok" : "missing"}`}>
                  {p.requires_key ? (p.has_key ? "key set" : "no key") : "no key needed"}
                </span>
              </span>
            </div>
            {probe[p.id] && (
              <div className={`provider-probe ${probe[p.id].ok ? "ok" : "err"}`}>
                {probe[p.id].ok ? "✓ " : "✕ "}
                {probe[p.id].detail}
              </div>
            )}
            {p.requires_key && (
              <div className="key-entry">
                <input
                  type="password"
                  placeholder={`${p.label} API key`}
                  aria-label={`${p.label} API key`}
                  value={keyDraft[p.id] ?? ""}
                  onChange={(e) => setKeyDraft((d) => ({ ...d, [p.id]: e.target.value }))}
                />
                <button onClick={() => saveKey(p.id)} disabled={!(keyDraft[p.id] ?? "").trim()}>
                  Save
                </button>
              </div>
            )}
            <div className="model-row">
              {(p.models.length ? p.models : [p.default_model].filter(Boolean)).map((m) => (
                <button
                  key={m}
                  className={p.id === active.provider && m === active.model ? "model active" : "model"}
                  onClick={() => onPick(p.id, m)}
                  disabled={p.requires_key && !p.has_key}
                >
                  {m}
                </button>
              ))}
            </div>
          </li>
        ))}
      </ul>
    </>
  );
}

/* ---------------- Capabilities: web search ---------------- */

function CapabilitiesPage() {
  const [searchProvider, setSearchProvider] = useState("ddg");
  const [searxngUrl, setSearxngUrl] = useState("");
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    settingsApi
      .get()
      .then((s) => {
        setSearchProvider(s.search_provider ?? "ddg");
        setSearxngUrl(s.searxng_url ?? "");
      })
      .catch(() => {});
  }, []);

  function save(next: { search_provider?: string; searxng_url?: string }) {
    void settingsApi
      .save({ search_provider: searchProvider, searxng_url: searxngUrl, ...next })
      .catch((e) => setErr(String(e)));
  }

  return (
    <>
      {err && <div className="settings-err">{err}</div>}
      <label className="field-label" htmlFor="cap-search">Web search backend</label>
      <div className="profile-form">
        <select
          id="cap-search"
          value={searchProvider}
          onChange={(e) => {
            setSearchProvider(e.target.value);
            save({ search_provider: e.target.value });
          }}
        >
          <option value="ddg">DuckDuckGo (keyless, default)</option>
          <option value="searxng">SearXNG (self-hosted, privacy-respecting)</option>
        </select>
        {searchProvider === "searxng" && (
          <input
            placeholder="SearXNG base URL (e.g. http://localhost:8888)"
            aria-label="SearXNG base URL"
            value={searxngUrl}
            onChange={(e) => setSearxngUrl(e.target.value)}
            onBlur={() => save({})}
          />
        )}
      </div>
    </>
  );
}

/* ---------------- Skills table ---------------- */

function SkillsPage({ skills }: { skills: SkillSummary[] }) {
  return (
    <>
      <p className="settings-hint">
        Skills are markdown instruction packs in the <code>skills/</code> folder. Type{" "}
        <code>/</code> in the composer to invoke one; auto skills trigger on matching messages.
      </p>
      <table className="stable">
        <thead>
          <tr>
            <th>Skill</th>
            <th>Description</th>
            <th>Auto</th>
          </tr>
        </thead>
        <tbody>
          {skills.map((s) => (
            <tr key={s.name}>
              <td className="stable-name">/{s.name}</td>
              <td>{s.description || "—"}</td>
              <td>{s.auto ? (s.triggers ?? []).join(", ") || "yes" : "—"}</td>
            </tr>
          ))}
          {skills.length === 0 && (
            <tr>
              <td colSpan={3} className="stable-empty">No skills installed yet.</td>
            </tr>
          )}
        </tbody>
      </table>
    </>
  );
}

/* ---------------- Connectors (MCP) ---------------- */

function ConnectorsPage({ c }: { c: ConnectorControls }) {
  const [filter, setFilter] = useState<"all" | "connected" | "not">("all");
  const [showAdd, setShowAdd] = useState(false);
  const [mode, setMode] = useState<"stdio" | "remote">("remote");
  const [name, setName] = useState("");
  const [command, setCommand] = useState("");
  const [args, setArgs] = useState("");
  const [url, setUrl] = useState("");
  const [transport, setTransport] = useState("http");
  const [token, setToken] = useState("");
  const [auth, setAuth] = useState<"none" | "bearer" | "oauth">("none");

  const rows = c.servers.filter((s) =>
    filter === "all" ? true : filter === "connected" ? s.status === "connected" : s.status !== "connected",
  );

  function submit() {
    if (!name.trim()) return;
    if (mode === "stdio") {
      if (!command.trim()) return;
      c.onAdd({ name, command, args: args.trim() ? args.trim().split(/\s+/) : [] });
    } else {
      if (!url.trim()) return;
      if (auth === "oauth") c.onAddOAuth(name, url);
      else c.onAdd({ name, url, transport, auth_token: auth === "bearer" ? token.trim() || undefined : undefined });
    }
    setName("");
    setCommand("");
    setArgs("");
    setUrl("");
    setToken("");
    setShowAdd(false);
  }

  return (
    <>
      {c.err && <div className="settings-err">{c.err}</div>}
      <div className="settings-toolbar">
        <div className="filter-chips" role="group" aria-label="Filter connectors">
          {(
            [
              ["all", "All"],
              ["connected", "Connected"],
              ["not", "Not connected"],
            ] as const
          ).map(([id, label]) => (
            <button
              key={id}
              className={`filter-chip ${filter === id ? "active" : ""}`}
              onClick={() => setFilter(id)}
            >
              {label}
            </button>
          ))}
        </div>
        <span className="settings-toolbar-spacer" />
        <label className="settings-add-file">
          Install extension
          <input
            type="file"
            accept=".mcpb,.dxt,application/zip"
            style={{ display: "none" }}
            onChange={(e) => {
              const f = e.target.files?.[0];
              if (f) c.onInstall(f);
              e.target.value = "";
            }}
          />
        </label>
        <button className="settings-add" onClick={() => setShowAdd((v) => !v)}>
          {showAdd ? "Cancel" : "Add ▾"}
        </button>
      </div>

      {showAdd && (
        <div className="conn-add">
          <div className="conn-tabs">
            <button className={mode === "remote" ? "active" : ""} onClick={() => setMode("remote")}>
              Remote
            </button>
            <button className={mode === "stdio" ? "active" : ""} onClick={() => setMode("stdio")}>
              Local
            </button>
            <button className="conn-demo" onClick={c.onAddDemo}>
              + Demo
            </button>
          </div>
          <input placeholder="Name" aria-label="Connector name" value={name} onChange={(e) => setName(e.target.value)} />
          {mode === "stdio" ? (
            <>
              <input placeholder="Command (e.g. npx)" value={command} onChange={(e) => setCommand(e.target.value)} />
              <input placeholder="Args (space-separated)" value={args} onChange={(e) => setArgs(e.target.value)} />
            </>
          ) : (
            <>
              <input placeholder="URL (https://…/mcp)" value={url} onChange={(e) => setUrl(e.target.value)} />
              <select value={transport} onChange={(e) => setTransport(e.target.value)} aria-label="Transport">
                <option value="http">Streamable HTTP</option>
                <option value="sse">SSE (legacy)</option>
              </select>
              <select value={auth} onChange={(e) => setAuth(e.target.value as typeof auth)} aria-label="Auth">
                <option value="none">No auth</option>
                <option value="bearer">Bearer token</option>
                <option value="oauth">OAuth 2.1 (authorize in browser)</option>
              </select>
              {auth === "bearer" && (
                <input
                  type="password"
                  placeholder="Bearer token (stored in keychain)"
                  value={token}
                  onChange={(e) => setToken(e.target.value)}
                />
              )}
            </>
          )}
          <button className="conn-submit" onClick={submit}>
            {mode === "remote" && auth === "oauth" ? "Add OAuth connector" : "Add connector"}
          </button>
        </div>
      )}

      <table className="stable">
        <thead>
          <tr>
            <th className="stable-check" aria-label="Enabled" />
            <th>Connector</th>
            <th>Type</th>
            <th>Status</th>
            <th aria-label="Actions" />
          </tr>
        </thead>
        <tbody>
          {rows.map((s) => (
            <tr key={s.id}>
              <td className="stable-check">
                <input
                  type="checkbox"
                  aria-label={`Enable ${s.name}`}
                  checked={c.enabled.includes(s.id)}
                  disabled={s.status !== "connected"}
                  onChange={() => c.onToggle(s.id)}
                />
              </td>
              <td className="stable-name">
                {s.name}
                {s.source === "mcpb" && <span className="conn-badge conn-ext">extension{s.version ? ` v${s.version}` : ""}</span>}
                {s.auth_mode === "oauth" && <span className="conn-badge conn-ext">OAuth{s.authorized ? " ✓" : ""}</span>}
              </td>
              <td>{s.transport}</td>
              <td>
                <span className={`conn-status ${s.status}`}>{s.status}</span>
                {s.status === "connected" && <span className="stable-sub"> · {s.tool_count} tools</span>}
              </td>
              <td className="stable-actions">
                {s.auth_mode === "oauth" && !s.authorized && (
                  <button className="conn-authorize" title="Authorize (opens browser)" onClick={() => c.onAuthorize(s.id)}>
                    Authorize
                  </button>
                )}
                <button className="conn-del" title="Remove" aria-label={`Remove ${s.name}`} onClick={() => c.onRemove(s.id)}>
                  ✕
                </button>
              </td>
            </tr>
          ))}
          {rows.length === 0 && (
            <tr>
              <td colSpan={5} className="stable-empty">
                {filter === "all" ? "No connectors yet — use Add or Install extension." : "Nothing here."}
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </>
  );
}

/* ---------------- Plugins + marketplace ---------------- */

function PluginsPage({ p }: { p: PluginControls }) {
  const marketNames = new Set(p.market.map((m) => m.name));
  return (
    <>
      {p.err && <div className="settings-err">{p.err}</div>}
      <h3 className="settings-subhead">Installed</h3>
      <table className="stable">
        <thead>
          <tr>
            <th className="stable-check" aria-label="Enabled" />
            <th>Plugin</th>
            <th>Description</th>
            <th aria-label="Actions" />
          </tr>
        </thead>
        <tbody>
          {p.installed.map((pl) => (
            <tr key={pl.name}>
              <td className="stable-check">
                <input
                  type="checkbox"
                  aria-label={`Enable ${pl.name}`}
                  checked={p.enabled.includes(pl.name)}
                  onChange={() => p.onToggle(pl.name)}
                />
              </td>
              <td className="stable-name">{pl.name}</td>
              <td>{pl.description || "—"}</td>
              <td className="stable-actions">
                {marketNames.has(pl.name) && (
                  <button
                    className="conn-del"
                    title="Uninstall"
                    aria-label={`Uninstall ${pl.name}`}
                    disabled={p.busy === pl.name}
                    onClick={() => p.onUninstall(pl.name)}
                  >
                    ✕
                  </button>
                )}
              </td>
            </tr>
          ))}
          {p.installed.length === 0 && (
            <tr>
              <td colSpan={4} className="stable-empty">No plugins installed yet.</td>
            </tr>
          )}
        </tbody>
      </table>

      <h3 className="settings-subhead">Marketplace</h3>
      <p className="settings-hint">Vetted, offline plugins bundled with the app.</p>
      <table className="stable">
        <thead>
          <tr>
            <th>Plugin</th>
            <th>Category</th>
            <th>Description</th>
            <th aria-label="Actions" />
          </tr>
        </thead>
        <tbody>
          {p.market.map((m) => (
            <tr key={m.name}>
              <td className="stable-name">{m.name}</td>
              <td>
                <span className="badge-pill">{m.category}</span>
              </td>
              <td>{m.description}</td>
              <td className="stable-actions">
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
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  );
}
