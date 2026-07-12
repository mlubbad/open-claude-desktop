import { useEffect, useState } from "react";

import { type DirectoryEntry, mcp } from "../../api/client";
import { parseEnvLines, parseMcpJson, splitArgs } from "../../state/mcpConfig";
import { Icon } from "../Icon";
import { DirCard, DirEmpty } from "./DirCard";
import type { ConnectorControls } from "./types";

// Connectors (MCP): the server list + a three-tab add form (Remote / Local / JSON),
// plus a curated "Browse connectors" directory (P1-3) whose entries prefill the form.
export function ConnectorsPage({ c }: { c: ConnectorControls }) {
  const [filter, setFilter] = useState<"all" | "connected" | "not">("all");
  const [showAdd, setShowAdd] = useState(false);
  const [showBrowse, setShowBrowse] = useState(false);
  const [directory, setDirectory] = useState<DirectoryEntry[]>([]);
  // Which server's per-tool toggle list is expanded (P1-12).
  const [toolsFor, setToolsFor] = useState<string | null>(null);

  useEffect(() => {
    if (!showBrowse || directory.length > 0) return;
    mcp.directory().then(setDirectory).catch(() => {});
  }, [showBrowse, directory.length]);
  const [mode, setMode] = useState<"stdio" | "remote" | "json">("remote");
  const [name, setName] = useState("");
  const [command, setCommand] = useState("");
  const [args, setArgs] = useState("");
  const [envText, setEnvText] = useState("");
  const [jsonText, setJsonText] = useState("");
  const [jsonErr, setJsonErr] = useState<string | null>(null);
  const [url, setUrl] = useState("");
  const [transport, setTransport] = useState("http");
  const [token, setToken] = useState("");
  const [auth, setAuth] = useState<"none" | "bearer" | "oauth">("none");

  const rows = c.servers.filter((s) =>
    filter === "all" ? true : filter === "connected" ? s.status === "connected" : s.status !== "connected",
  );

  function reset() {
    setName("");
    setCommand("");
    setArgs("");
    setEnvText("");
    setJsonText("");
    setJsonErr(null);
    setUrl("");
    setToken("");
    setShowAdd(false);
  }

  // A directory pick PREFILLS the add form (never adds silently): the user reviews
  // the command/args — and fills any required env key — before confirming.
  function applyEntry(e: DirectoryEntry) {
    setShowBrowse(false);
    setShowAdd(true);
    setName(e.name);
    if (e.url) {
      setMode("remote");
      setUrl(e.url);
      setTransport(e.transport === "sse" ? "sse" : "http");
    } else {
      setMode("stdio");
      setCommand(e.command ?? "");
      setArgs((e.args ?? []).map((a) => (a.includes(" ") ? `"${a}"` : a)).join(" "));
      setEnvText(e.env_keys.map((k) => `${k}=`).join("\n"));
    }
  }

  function submit() {
    if (mode === "json") {
      // Paste the Claude-Desktop-style config JSON verbatim — quoting, args arrays,
      // and env come through exactly, no re-typing.
      try {
        for (const body of parseMcpJson(jsonText)) c.onAdd(body);
      } catch (e) {
        setJsonErr(e instanceof Error ? e.message : String(e));
        return;
      }
      reset();
      return;
    }
    if (!name.trim()) return;
    if (mode === "stdio") {
      if (!command.trim()) return;
      // Quote-aware split: a Windows path with spaces stays ONE argument when quoted.
      c.onAdd({ name, command, args: splitArgs(args), env: parseEnvLines(envText) });
    } else {
      if (!url.trim()) return;
      if (auth === "oauth") c.onAddOAuth(name, url);
      else c.onAdd({ name, url, transport, auth_token: auth === "bearer" ? token.trim() || undefined : undefined });
    }
    reset();
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
        <button className="settings-add" onClick={() => setShowBrowse((v) => !v)}>
          {showBrowse ? "Close" : "Browse"}
        </button>
        <button className="settings-add" onClick={() => setShowAdd((v) => !v)}>
          {showAdd ? "Cancel" : "Add ▾"}
        </button>
      </div>

      {showBrowse && (
        <div className="dir-grid" aria-label="Connector directory">
          {directory.map((e) => (
            <DirCard key={e.id} icon="sliders" title={e.name}
                     badges={e.tags.includes("official")
                       ? <span className="badge-pill">official</span> : undefined}>
              <p className="dir-card-desc">{e.description}</p>
              <div className="dir-card-actions">
                <span className="dir-card-actions-right">
                  <button className="conn-authorize"
                          title="Prefill the add form with this connector"
                          onClick={() => applyEntry(e)}>
                    Use
                  </button>
                </span>
              </div>
            </DirCard>
          ))}
          {directory.length === 0 && <DirEmpty>Loading directory…</DirEmpty>}
        </div>
      )}

      {showAdd && (
        <div className="conn-add">
          <div className="conn-tabs">
            <button className={mode === "remote" ? "active" : ""} onClick={() => setMode("remote")}>
              Remote
            </button>
            <button className={mode === "stdio" ? "active" : ""} onClick={() => setMode("stdio")}>
              Local
            </button>
            <button className={mode === "json" ? "active" : ""} onClick={() => setMode("json")}>
              Import JSON
            </button>
          </div>
          {mode !== "json" && (
            <input placeholder="Name" aria-label="Connector name" value={name} onChange={(e) => setName(e.target.value)} />
          )}
          {mode === "json" ? (
            <>
              <p className="settings-hint" style={{ margin: 0 }}>
                Paste the server's config JSON — the same <code>mcpServers</code> shape
                Claude Desktop uses (command, args, env all preserved exactly).
              </p>
              <textarea
                className="conn-json"
                rows={8}
                spellCheck={false}
                placeholder={'{\n  "mcpServers": {\n    "Windows-MCP": {\n      "command": "uv",\n      "args": ["--directory", "C:\\\\path with spaces", "run", "windows-mcp"],\n      "env": {"MODE": "local"}\n    }\n  }\n}'}
                aria-label="MCP config JSON"
                value={jsonText}
                onChange={(e) => {
                  setJsonText(e.target.value);
                  setJsonErr(null);
                }}
              />
              {jsonErr && <div className="settings-err">{jsonErr}</div>}
            </>
          ) : mode === "stdio" ? (
            <>
              <input placeholder="Command (e.g. npx, uv)" value={command} onChange={(e) => setCommand(e.target.value)} />
              <input
                placeholder={'Args — quote paths with spaces: --directory "C:\\path with spaces" run server'}
                aria-label="Command arguments"
                value={args}
                onChange={(e) => setArgs(e.target.value)}
              />
              <textarea
                className="conn-env"
                rows={3}
                spellCheck={false}
                placeholder={"Environment variables (one per line)\nMODE=local\nAPI_KEY=…"}
                aria-label="Environment variables"
                value={envText}
                onChange={(e) => setEnvText(e.target.value)}
              />
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
            {mode === "json" ? "Import" : mode === "remote" && auth === "oauth" ? "Add OAuth connector" : "Add connector"}
          </button>
        </div>
      )}

      <div className="dir-grid">
        {rows.map((s) => (
          <DirCard
            key={s.id}
            className={s.status === "connected" ? "is-on" : undefined}
            icon="sliders"
            title={s.name}
            badges={
              <>
                {s.source === "mcpb" && <span className="badge-pill">extension{s.version ? ` v${s.version}` : ""}</span>}
                {s.auth_mode === "oauth" && <span className="badge-pill">OAuth{s.authorized ? " ✓" : ""}</span>}
              </>
            }
          >
            <p className="dir-card-desc">
              <span className={`conn-status ${s.status}`}>{s.status}</span>
              {" · "}{s.transport}
              {s.status === "connected" && <> · {s.tool_count} tools</>}
            </p>
            {s.status === "error" && s.detail && (
              <p className="dir-card-err" title={s.detail}>{s.detail}</p>
            )}
            {s.tools.length > 0 && (
              <div className="conn-tools">
                <button
                  className="conn-tools-head"
                  aria-expanded={toolsFor === s.id}
                  onClick={() => setToolsFor((v) => (v === s.id ? null : s.id))}
                >
                  Tools ({s.tools.length - s.disabled_tools.length}/{s.tools.length} on)
                </button>
                {toolsFor === s.id && (
                  <ul className="conn-tools-list">
                    {s.tools.map((t) => (
                      <li key={t}>
                        <label>
                          <input
                            type="checkbox"
                            checked={!s.disabled_tools.includes(t)}
                            aria-label={`Enable tool ${t}`}
                            onChange={(e) => c.onToolToggle(s.id, t, e.target.checked)}
                          />
                          <span className="conn-tool-name">{t}</span>
                        </label>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            )}
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
                {s.source === "mcpb" && !!s.repository && (
                  c.updates[s.id]?.latest ? (
                    <button
                      className="conn-authorize"
                      title={c.updates[s.id].notes || "Download and reinstall this extension"}
                      aria-label={`Update ${s.name}`}
                      disabled={c.updating === s.id}
                      onClick={() => c.onUpdate(s.id)}
                    >
                      {c.updating === s.id ? "Updating…" : `Update to v${c.updates[s.id].latest}`}
                    </button>
                  ) : (
                    <button
                      className="conn-authorize"
                      title="Check the extension's GitHub releases for a newer bundle"
                      aria-label={`Check updates for ${s.name}`}
                      disabled={c.updating === s.id}
                      onClick={() => c.onCheckUpdate(s.id)}
                    >
                      {c.updating === s.id ? "Checking…" : c.updates[s.id] ? "Up to date" : "Check for updates"}
                    </button>
                  )
                )}
                {s.status === "error" && (
                  <button
                    className="conn-authorize"
                    title="Re-connect this server (first-run downloads are usually cached by now)"
                    aria-label={`Retry ${s.name}`}
                    disabled={c.retrying === s.id}
                    onClick={() => c.onRetry(s.id)}
                  >
                    {c.retrying === s.id ? "Retrying…" : "Retry"}
                  </button>
                )}
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
          </DirCard>
        ))}
      </div>
      {rows.length === 0 && (
        <DirEmpty>
          {filter === "all" ? "No connectors yet — use Add or Install extension." : "Nothing here."}
        </DirEmpty>
      )}
    </>
  );
}
