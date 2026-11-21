import { useRef, useState } from "react";

import { Icon } from "../Icon";
import { LockedButton, Row, Section, Toggle } from "./controls";
import { type ConnectorControls, localServers } from "./types";

// Desktop app → Extensions: the local (stdio) MCP servers running ON this machine,
// including one-click .mcpb/.dxt bundles — Claude Desktop's "Installed on your
// computer" list. Remote connectors live under Customize → Connectors; this page is
// deliberately the machine-local subset, matching the reference.
export function ExtensionsPage({ c }: { c: ConnectorControls }) {
  const fileRef = useRef<HTMLInputElement>(null);
  const [advanced, setAdvanced] = useState(false);
  const local = localServers(c.servers);

  return (
    <>
      {c.err && <div className="settings-err">{c.err}</div>}
      <div className="set-page-intro">
        <p className="settings-hint">
          Allow Claude to directly interact with apps, data, and tools on your computer.
        </p>
        <LockedButton>Browse extensions</LockedButton>
      </div>

      <Section title="Installed on your computer">
        {local.length === 0 && (
          <p className="settings-hint">Nothing installed yet — drop a .mcpb/.dxt bundle below, or add a local command under Connectors.</p>
        )}
        {local.map((s) => (
          <Row
            key={s.id}
            label={s.name}
            desc={s.status === "error" ? s.detail || "error" : `${s.tool_count} tools`}
          >
            {s.status === "error" && (
              <button className="set-btn" onClick={() => c.onRetry(s.id)} disabled={c.retrying === s.id}>
                {c.retrying === s.id ? "Retrying…" : "Retry"}
              </button>
            )}
            <button
              className="set-btn danger"
              aria-label={`Remove ${s.name}`}
              onClick={() => c.onRemove(s.id)}
            >
              Remove
            </button>
          </Row>
        ))}
      </Section>

      <button className="set-btn" onClick={() => setAdvanced((v) => !v)} aria-expanded={advanced}>
        Advanced settings
      </button>
      <label className="set-dropzone">
        <Icon name="cloud-up" size={14} /> Drag .MCPB or .DXT files here to install — or click to choose
        <input
          ref={fileRef}
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

      {advanced && (
        <>
          <Section title="Extension settings">
            <Row label="Enable auto-updates for extensions"
                 desc="Automatically update extensions when new versions are available." locked>
              <Toggle label="Enable auto-updates for extensions" on={false} disabled />
            </Row>
            <Row label="Use built-in Node.js for MCP"
                 desc="If enabled, Claude will never use the system Node.js for extension MCP servers." locked>
              <Toggle label="Use built-in Node.js for MCP" on={false} disabled />
            </Row>
          </Section>
          <Section title="Extension developer">
            <div className="set-warning">
              <b>Developer tools warning.</b> These tools are intended for extension developers
              only. Using them incorrectly may cause extensions to malfunction.
            </div>
            <div className="set-btn-row">
              <button className="set-btn primary" onClick={() => fileRef.current?.click()}>
                Install extension
              </button>
              <LockedButton>Install unpacked extension</LockedButton>
              <LockedButton>Open extensions folder</LockedButton>
            </div>
          </Section>
        </>
      )}
    </>
  );
}
