import { useEffect, useRef, useState } from "react";

import {
  type AddMcpBody,
  type MarketplacePlugin,
  type MarketplaceSource,
  type McpServer,
  type PluginSummary,
  type ProviderInfo,
  providers,
  settings as settingsApi,
  type SkillSummary,
  type UserProfile,
} from "../api/client";
import { pickerModels } from "../state/modelMeta";
import { Icon } from "./Icon";

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

export interface SkillControls {
  list: SkillSummary[];
  busy: boolean;
  allowRemote: boolean;
  importFile: (filename: string, content: string) => Promise<string | null>;
  importFromRepo: (url: string, ref?: string) => Promise<string | null>;
  onRemove: (name: string) => void;
}

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
  sources: MarketplaceSource[];
  allowRemote: boolean;
  enabled: string[];
  err: string | null;
  busy: string | null;
  onToggle: (name: string) => void;
  onInstall: (name: string) => void;
  onUninstall: (name: string) => void;
  onAddSource: (url: string, ref?: string, name?: string) => Promise<string | null>;
  onRemoveSource: (id: string) => void;
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
  skills: SkillControls;
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
            {page === "skills" && <SkillsPage c={skills} />}
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
  // Per-provider models the chat picker shows ({} entry = the newest-few default).
  const [visible, setVisible] = useState<Record<string, string[]>>({});

  async function refresh() {
    try {
      setList(await providers.list());
    } catch (e) {
      setErr(String(e));
    }
  }
  useEffect(() => {
    void refresh();
    settingsApi.get().then((s) => setVisible(s.visible_models ?? {})).catch(() => {});
  }, []);

  // Is this model currently shown in the chat picker? (explicit selection, or the
  // newest-few default when the provider has no selection yet)
  function shown(p: ProviderInfo, m: string): boolean {
    return pickerModels(p.models, visible[p.id], "").includes(m);
  }

  // Toggle a model's picker visibility. The first toggle materializes the provider's
  // default into an explicit list; hiding the last visible model is a no-op.
  function toggleShown(p: ProviderInfo, m: string) {
    const cur = pickerModels(p.models, visible[p.id], "");
    const next = cur.includes(m) ? cur.filter((x) => x !== m) : [...cur, m];
    if (next.length === 0) return;
    const all = { ...visible, [p.id]: p.models.filter((x) => next.includes(x)) };
    setVisible(all);
    void settingsApi.save({ visible_models: all }).catch((e) => setErr(String(e)));
  }

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
        keychain and never read back. Click a model to use it now; the eye chooses which
        models appear in the chat's model picker (a short newest-first list by default).
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
              {(p.models.length ? p.models : [p.default_model].filter(Boolean)).map((m) => {
                const isActive = p.id === active.provider && m === active.model;
                const isShown = shown(p, m);
                return (
                  <span key={m} className={`model-chip ${isActive ? "active" : ""} ${isShown ? "" : "off"}`}>
                    <button
                      className="model-pick"
                      onClick={() => onPick(p.id, m)}
                      disabled={p.requires_key && !p.has_key}
                    >
                      {m}
                    </button>
                    <button
                      className="model-vis"
                      role="switch"
                      aria-checked={isShown}
                      aria-label={`Show ${m} in the chat model picker`}
                      title={isShown ? "Shown in the chat model picker — click to hide" : "Hidden from the chat model picker — click to show"}
                      onClick={() => toggleShown(p, m)}
                    >
                      <Icon name="eye" size={12} />
                    </button>
                  </span>
                );
              })}
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
  const [codeExecution, setCodeExecution] = useState("auto");
  const [permissionMode, setPermissionMode] = useState("ask");
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    settingsApi
      .get()
      .then((s) => {
        setSearchProvider(s.search_provider ?? "ddg");
        setSearxngUrl(s.searxng_url ?? "");
        setCodeExecution(s.code_execution ?? "auto");
        setPermissionMode(s.permission_mode ?? "ask");
      })
      .catch(() => {});
  }, []);

  function save(next: {
    search_provider?: string;
    searxng_url?: string;
    code_execution?: string;
    permission_mode?: string;
  }) {
    void settingsApi
      .save({
        search_provider: searchProvider,
        searxng_url: searxngUrl,
        code_execution: codeExecution,
        permission_mode: permissionMode,
        ...next,
      })
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

      <label className="field-label" htmlFor="cap-exec">Code execution</label>
      <div className="profile-form">
        <select
          id="cap-exec"
          value={codeExecution}
          onChange={(e) => {
            setCodeExecution(e.target.value);
            save({ code_execution: e.target.value });
          }}
        >
          <option value="auto">Automatic — Docker sandbox if available, else this device</option>
          <option value="docker">Docker only — strongest isolation (requires Docker)</option>
          <option value="local">This device — jailed workspace, resource-limited</option>
          <option value="off">Off — never run code</option>
        </select>
        <p className="settings-hint">
          Lets the agent actually run Python and produce files (a CSV, a chart). Docker gives
          the strongest isolation; local mode runs in a confined workspace folder with
          CPU/memory/output/time limits. How often it asks you first is set below.
        </p>
      </div>

      <label className="field-label" htmlFor="cap-perm">Approvals &amp; autonomy</label>
      <div className="profile-form">
        <select
          id="cap-perm"
          value={permissionMode}
          onChange={(e) => {
            setPermissionMode(e.target.value);
            save({ permission_mode: e.target.value });
          }}
        >
          <option value="strict">Approve every step — confirm before each tool runs</option>
          <option value="ask">Approve sensitive steps — confirm code, shell, file &amp; data actions (default)</option>
          <option value="auto">Autonomous — run everything without asking (auto-pilot)</option>
        </select>
        <p className="settings-hint">
          Controls how often the agent pauses for your approval. “Autonomous” lets it run
          code and multi-step tasks end-to-end without prompting — convenient for trusted
          work, but it will execute tool actions (including code) on its own. The Plan-mode
          toggle in the composer still works on top of this.
        </p>
      </div>
    </>
  );
}

/* ---------------- Directory shared bits (Skills / Connectors / Plugins) ---------------- */

// Escape closes just this dialog. A capture-phase window listener runs before the
// app-wide Escape handler (which would otherwise close the whole Settings modal) and
// stops it, regardless of where focus currently sits.
function useDialogEscape(onClose: () => void): void {
  const ref = useRef(onClose);
  ref.current = onClose;
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") {
        e.stopPropagation();
        e.preventDefault();
        ref.current();
      }
    }
    window.addEventListener("keydown", onKey, true);
    return () => window.removeEventListener("keydown", onKey, true);
  }, []);
}

// The search box atop each Directory grid page.
function DirToolbar({ q, onQ, placeholder }: { q: string; onQ: (v: string) => void; placeholder: string }) {
  return (
    <div className="dir-search">
      <Icon name="search" size={14} />
      <input
        value={q}
        onChange={(e) => onQ(e.target.value)}
        placeholder={placeholder}
        aria-label={placeholder}
      />
    </div>
  );
}

/* ---------------- Skills directory (browse + import) ---------------- */

function SkillsPage({ c }: { c: SkillControls }) {
  const [q, setQ] = useState("");
  const [showRepo, setShowRepo] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const rows = c.list.filter((s) =>
    (s.name + " " + (s.description ?? "")).toLowerCase().includes(q.trim().toLowerCase()),
  );

  async function onFile(file: File | undefined) {
    if (!file) return;
    setErr(null);
    const text = await file.text();
    const failure = await c.importFile(file.name, text);
    if (failure) setErr(failure);
  }

  return (
    <>
      {err && <div className="settings-err">{err}</div>}
      <p className="settings-hint">
        Skills are markdown instruction packs. Type <code>/</code> in the composer to invoke one;
        auto skills trigger on matching messages. Import your own or sync a repository of skills.
      </p>
      <div className="settings-toolbar">
        <DirToolbar q={q} onQ={setQ} placeholder="Search skills…" />
        <span className="settings-toolbar-spacer" />
        <label className="settings-add-file">
          Import skill
          <input
            ref={fileRef}
            type="file"
            accept=".md,.markdown,text/markdown,text/plain"
            style={{ display: "none" }}
            onChange={(e) => {
              void onFile(e.target.files?.[0]);
              e.target.value = "";
            }}
          />
        </label>
        <button className="settings-add" onClick={() => setShowRepo(true)}>
          <Icon name="plus" size={13} /> Add from repository
        </button>
      </div>
      <div className="dir-grid">
        {rows.map((s) => (
          <div className="dir-card" key={s.name}>
            <div className="dir-card-head">
              <span className="dir-card-icon"><Icon name="bulb" size={16} /></span>
              <span className="dir-card-title">/{s.name}</span>
              {s.auto && <span className="badge-pill">auto</span>}
              {s.imported && <span className="badge-pill dir-origin">imported</span>}
            </div>
            <p className="dir-card-desc">{s.description || "No description."}</p>
            <div className="dir-card-actions">
              {s.auto && (s.triggers ?? []).length > 0 ? (
                <span className="dir-card-foot">Triggers: {(s.triggers ?? []).join(", ")}</span>
              ) : (
                <span />
              )}
              {s.imported && (
                <button
                  className="dir-remove"
                  title="Remove imported skill"
                  aria-label={`Remove ${s.name}`}
                  onClick={() => c.onRemove(s.name)}
                >
                  <Icon name="x" size={14} />
                </button>
              )}
            </div>
          </div>
        ))}
      </div>
      {rows.length === 0 && (
        <div className="dir-empty">{c.list.length === 0 ? "No skills yet — import one." : "No matches."}</div>
      )}
      {showRepo && (
        <RepoSyncModal
          title="Add skills from a repository"
          blurb="Copy the markdown skill files from a GitHub repository or git URL into your skills."
          allowRemote={c.allowRemote}
          onSync={(url, ref) => c.importFromRepo(url, ref)}
          onClose={() => setShowRepo(false)}
        />
      )}
    </>
  );
}

// Shared "sync from a git URL" modal used by the Skills and Plugins directories.
function RepoSyncModal({
  title,
  blurb,
  allowRemote,
  onSync,
  onClose,
}: {
  title: string;
  blurb: string;
  allowRemote: boolean;
  onSync: (url: string, ref: string) => Promise<string | null>;
  onClose: () => void;
}) {
  const [url, setUrl] = useState("");
  const [ref, setRef] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  useDialogEscape(onClose); // Escape closes only this dialog, not the whole Settings modal

  async function submit() {
    if (!url.trim()) return;
    setBusy(true);
    setErr(null);
    const failure = await onSync(url.trim(), ref.trim());
    setBusy(false);
    if (failure) setErr(failure);
    else onClose();
  }

  return (
    <div className="settings-overlay" onClick={onClose}>
      <div
        className="add-market-modal"
        role="dialog"
        aria-modal="true"
        aria-label={title}
        onClick={(e) => e.stopPropagation()}
      >
        <header className="add-market-head">
          <h2>{title}</h2>
          <button className="settings-close" aria-label="Close" title="Close" onClick={onClose}>✕</button>
        </header>
        <div className="add-market-form">
          <p className="settings-hint" style={{ margin: "0 0 10px" }}>{blurb}</p>
          {!allowRemote && (
            <p className="settings-err">
              Remote syncing is disabled on this install (MARKETPLACE_ALLOW_REMOTE=0).
            </p>
          )}
          {err && <div className="settings-err">{err}</div>}
          <label className="field-label" htmlFor="rs-url">Repository URL</label>
          <input id="rs-url" placeholder="https://github.com/owner/repo.git"
                 value={url} onChange={(e) => setUrl(e.target.value)} />
          <label className="field-label" htmlFor="rs-ref">Branch or tag (optional)</label>
          <input id="rs-ref" placeholder="main" value={ref} onChange={(e) => setRef(e.target.value)} />
          <div className="drive-actions">
            <button className="btn-secondary" onClick={onClose}>Cancel</button>
            <button className="btn-primary" disabled={!url.trim() || busy || !allowRemote}
                    onClick={() => void submit()}>
              {busy ? "Syncing…" : "Sync"}
            </button>
          </div>
        </div>
      </div>
    </div>
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

      <div className="dir-grid">
        {rows.map((s) => (
          <div className={`dir-card ${s.status === "connected" ? "is-on" : ""}`} key={s.id}>
            <div className="dir-card-head">
              <span className="dir-card-icon"><Icon name="sliders" size={16} /></span>
              <span className="dir-card-title">{s.name}</span>
              {s.source === "mcpb" && <span className="badge-pill">extension{s.version ? ` v${s.version}` : ""}</span>}
              {s.auth_mode === "oauth" && <span className="badge-pill">OAuth{s.authorized ? " ✓" : ""}</span>}
            </div>
            <p className="dir-card-desc">
              <span className={`conn-status ${s.status}`}>{s.status}</span>
              {" · "}{s.transport}
              {s.status === "connected" && <> · {s.tool_count} tools</>}
            </p>
            <div className="dir-card-actions">
              <label className="dir-toggle">
                <input
                  type="checkbox"
                  aria-label={`Enable ${s.name}`}
                  checked={c.enabled.includes(s.id)}
                  disabled={s.status !== "connected"}
                  onChange={() => c.onToggle(s.id)}
                />
                Enabled
              </label>
              <span className="dir-card-actions-right">
                {s.auth_mode === "oauth" && !s.authorized && (
                  <button className="conn-authorize" title="Authorize (opens browser)" onClick={() => c.onAuthorize(s.id)}>
                    Authorize
                  </button>
                )}
                <button className="dir-remove" title="Remove" aria-label={`Remove ${s.name}`} onClick={() => c.onRemove(s.id)}>
                  <Icon name="x" size={14} />
                </button>
              </span>
            </div>
          </div>
        ))}
      </div>
      {rows.length === 0 && (
        <div className="dir-empty">
          {filter === "all" ? "No connectors yet — use Add or Install extension." : "Nothing here."}
        </div>
      )}
    </>
  );
}

/* ---------------- Plugins + marketplace ---------------- */

function PluginsPage({ p }: { p: PluginControls }) {
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
              <div className="dir-card" key={pl.name}>
                <div className="dir-card-head">
                  <span className="dir-card-icon"><Icon name="panel" size={16} /></span>
                  <span className="dir-card-title">{pl.name}</span>
                </div>
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
              </div>
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
          <div className="dir-card" key={m.name}>
            <div className="dir-card-head">
              <span className="dir-card-icon"><Icon name="panel" size={16} /></span>
              <span className="dir-card-title">{m.name}</span>
              <span className="badge-pill">{m.category}</span>
              {m.origin && m.origin !== "bundled" && (
                <span className="badge-pill dir-origin" title={`From ${m.origin}`}>{m.origin}</span>
              )}
            </div>
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
          </div>
        ))}
        {marketRows.length === 0 && <div className="dir-empty">No matches.</div>}
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
  const [url, setUrl] = useState("");
  const [ref, setRef] = useState("");
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  useDialogEscape(onClose); // Escape closes only this dialog, not the whole Settings modal

  async function submit() {
    if (!url.trim()) return;
    setBusy(true);
    setErr(null);
    const failure = await p.onAddSource(url.trim(), ref.trim(), name.trim());
    setBusy(false);
    if (failure) setErr(failure);
    else onClose();
  }

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
