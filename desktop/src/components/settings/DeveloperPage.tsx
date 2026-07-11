import { useState } from "react";

import { LockedButton, Row, Section } from "./controls";
import type { ConnectorControls } from "./types";

// Desktop app → Developer: the raw view of local MCP servers (command, args, status)
// with an mcpServers-style JSON export — Claude Desktop's "Local MCP servers" page.
// Editing happens in Customize → Connectors; this page is the inspector.
export function DeveloperPage({ c }: { c: ConnectorControls }) {
  const [copied, setCopied] = useState(false);
  const local = c.servers.filter((s) => s.transport === "stdio");

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
    </>
  );
}
