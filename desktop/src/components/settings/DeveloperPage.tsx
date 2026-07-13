import { useState } from "react";

import { diagnostics } from "../../api/client";
import { LockedButton, Row, Section } from "./controls";
import { type ConnectorControls, localServers } from "./types";

// Desktop app → Developer: the raw view of local MCP servers (command, args, status)
// with an mcpServers-style JSON export — Claude Desktop's "Local MCP servers" page.
// Editing happens in Customize → Connectors; this page is the inspector.
export function DeveloperPage({ c }: { c: ConnectorControls }) {
  const [copied, setCopied] = useState(false);
  const [diagBusy, setDiagBusy] = useState(false);
  const [diagErr, setDiagErr] = useState<string | null>(null);
  const local = localServers(c.servers);

  // Fetch the redacted diagnostics snapshot and save it as a JSON file the user can
  // attach to a bug report. Everything runs client-side (Blob + object URL).
  async function exportDiagnostics() {
    setDiagBusy(true);
    setDiagErr(null);
    try {
      const data = await diagnostics.get();
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = "open-claude-desktop-diagnostics.json";
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    } catch (e) {
      setDiagErr(String(e));
    } finally {
      setDiagBusy(false);
    }
  }

  const configJson = JSON.stringify(
    {
      mcpServers: Object.fromEntries(
        local.map((s) => [s.id, { command: s.command, args: s.args }]),
      ),
    },
    null,
    2,
  );

  function copyConfig() {
    void navigator.clipboard?.writeText(configJson).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    });
  }

  return (
    <>
      <div className="set-page-intro">
        <p className="settings-hint">
          Local MCP servers this app launches. Add or edit them under Customize → Connectors
          (including JSON import).
        </p>
        <button className="set-btn" onClick={copyConfig}>{copied ? "Copied ✓" : "Copy config"}</button>
      </div>

      <Section title="Local MCP servers">
        {local.length === 0 && <p className="settings-hint">No local servers configured.</p>}
        {local.map((s) => (
          <div key={s.id} className="set-devcard">
            <div className="set-devcard-head">
              <b>{s.name}</b>
              <span className={`set-status ${s.status}`}>{s.status}</span>
            </div>
            <dl className="set-devcard-body">
              <dt>Command</dt>
              <dd><code>{s.command || "—"}</code></dd>
              <dt>Arguments</dt>
              <dd><code>{(s.args ?? []).join(" ") || "—"}</code></dd>
              {s.detail && (
                <>
                  <dt>Detail</dt>
                  <dd className="set-muted">{s.detail}</dd>
                </>
              )}
            </dl>
            <div className="set-btn-row">
              <LockedButton>View logs</LockedButton>
            </div>
          </div>
        ))}
      </Section>

      <Section title="Config (read-only)">
        <Row label="mcpServers JSON" desc="The equivalent of Claude Desktop's config file for the servers above." stacked>
          <pre className="set-code">{configJson}</pre>
        </Row>
      </Section>

      <Section title="Diagnostics">
        <Row label="Export diagnostics"
             desc="Download a redacted snapshot (app version, platform, settings, data counts) for a bug report. Contains no API keys, and your profile is reduced to a presence flag.">
          <button className="set-btn" onClick={exportDiagnostics} disabled={diagBusy}
                  aria-label="Export diagnostics">
            {diagBusy ? "Exporting…" : "Export diagnostics"}
          </button>
        </Row>
        {diagErr && <div className="settings-err">{diagErr}</div>}
      </Section>
    </>
  );
}
