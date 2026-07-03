import { useRef, useState } from "react";

import type { AddMcpBody, McpServer } from "../api/client";

// Manage MCP connectors: list servers with status + tool count, enable them for the
// session, add a stdio (local command) or remote (Streamable-HTTP/SSE url) server,
// one-click-install a .mcpb/.dxt extension bundle, or add the bundled demo. Remote
// auth tokens go to the backend keychain, never stored here.
export function ConnectorsPanel({
  servers,
  enabled,
  err,
  onAdd,
  onAddDemo,
  onInstall,
  onRemove,
  onToggle,
  onClose,
}: {
  servers: McpServer[];
  enabled: string[];
  err: string | null;
  onAdd: (body: AddMcpBody) => void;
  onAddDemo: () => void;
  onInstall: (file: File) => void;
  onRemove: (sid: string) => void;
  onToggle: (sid: string) => void;
  onClose: () => void;
}) {
  const fileRef = useRef<HTMLInputElement>(null);
  const [mode, setMode] = useState<"stdio" | "remote">("remote");
  const [name, setName] = useState("");
  const [command, setCommand] = useState("");
  const [args, setArgs] = useState("");
  const [url, setUrl] = useState("");
  const [transport, setTransport] = useState("http");
  const [token, setToken] = useState("");

  function submit() {
    if (!name.trim()) return;
    if (mode === "stdio") {
      if (!command.trim()) return;
      onAdd({ name, command, args: args.trim() ? args.trim().split(/\s+/) : [] });
    } else {
      if (!url.trim()) return;
      onAdd({ name, url, transport, auth_token: token.trim() || undefined });
    }
    setName("");
    setCommand("");
    setArgs("");
    setUrl("");
    setToken("");
  }

  return (
    <div className="settings-overlay" onClick={onClose}>
      <div className="settings" onClick={(e) => e.stopPropagation()}>
        <div className="settings-head">
          <h2>Connectors (MCP)</h2>
          <div className="conn-head-actions">
            <button
              className="conn-install"
              title="Install a .mcpb / .dxt extension bundle"
              onClick={() => fileRef.current?.click()}
            >
              ⬇ Install extension
            </button>
            <button onClick={onClose}>✕</button>
          </div>
        </div>
        <input
          ref={fileRef}
          type="file"
          accept=".mcpb,.dxt,application/zip"
          style={{ display: "none" }}
          onChange={(e) => {
            const f = e.target.files?.[0];
            if (f) onInstall(f);
            e.target.value = ""; // allow re-selecting the same file
          }}
        />
        {err && <div className="settings-err">{err}</div>}

        <ul className="conn-list">
          {servers.map((s) => (
            <li key={s.id}>
              <label className="conn-enable">
                <input
                  type="checkbox"
                  checked={enabled.includes(s.id)}
                  disabled={s.status !== "connected"}
                  onChange={() => onToggle(s.id)}
                />
              </label>
              <span className="conn-meta">
                <span className="conn-name">{s.name}</span>
                <span className="conn-sub">
                  <span className="conn-badge">{s.transport}</span>
                  {s.source === "mcpb" && (
                    <span className="conn-badge conn-ext">extension{s.version ? ` v${s.version}` : ""}</span>
                  )}
                  <span className={`conn-status ${s.status}`}>{s.status}</span>
                  {s.status === "connected" && <> · {s.tool_count} tools</>}
                  {s.url && <> · {s.url}</>}
                </span>
              </span>
              <button className="conn-del" title="Remove" onClick={() => onRemove(s.id)}>
                ✕
              </button>
            </li>
          ))}
          {servers.length === 0 && <li className="conn-empty">No connectors yet</li>}
        </ul>

        <div className="conn-add">
          <div className="conn-tabs">
            <button className={mode === "remote" ? "active" : ""} onClick={() => setMode("remote")}>
              Remote
            </button>
            <button className={mode === "stdio" ? "active" : ""} onClick={() => setMode("stdio")}>
              Local
            </button>
            <button className="conn-demo" onClick={onAddDemo}>
              + Demo
            </button>
          </div>
          <input placeholder="Name" value={name} onChange={(e) => setName(e.target.value)} />
          {mode === "stdio" ? (
            <>
              <input placeholder="Command (e.g. npx)" value={command} onChange={(e) => setCommand(e.target.value)} />
              <input placeholder="Args (space-separated)" value={args} onChange={(e) => setArgs(e.target.value)} />
            </>
          ) : (
            <>
              <input placeholder="URL (https://…/mcp)" value={url} onChange={(e) => setUrl(e.target.value)} />
              <select value={transport} onChange={(e) => setTransport(e.target.value)}>
                <option value="http">Streamable HTTP</option>
                <option value="sse">SSE (legacy)</option>
              </select>
              <input
                type="password"
                placeholder="Bearer token (optional, stored in keychain)"
                value={token}
                onChange={(e) => setToken(e.target.value)}
              />
            </>
          )}
          <button className="conn-submit" onClick={submit}>
            Add connector
          </button>
        </div>
      </div>
    </div>
  );
}
