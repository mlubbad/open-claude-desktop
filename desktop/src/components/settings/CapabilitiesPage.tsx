import { useSettingsFields } from "../../state/useSettingsFields";
import { InlineSelect, LockedButton, Row, Section, Toggle } from "./controls";
import { ObservabilitySection } from "./ObservabilitySection";

// Capabilities, structured like Claude Desktop's page (Memory / General / Visuals /
// Code execution). Real controls: web-search backend, code-execution engine, and the
// approvals/autonomy mode. Everything without a backend renders disabled — memory
// toggles, tool-access mode, artifact master switches (those are per-chat via the
// composer's + menu), and network-egress allowlists.
export function CapabilitiesPage() {
  const { values, set, save, err } = useSettingsFields();
  const searchProvider = values?.search_provider ?? "ddg";
  const searxngUrl = values?.searxng_url ?? "";
  const codeExecution = values?.code_execution ?? "auto";
  const permissionMode = values?.permission_mode ?? "ask";
  const memorySearch = values?.memory_search ?? true;
  const autonomyPaused = values?.autonomy_paused ?? false;

  return (
    <>
      {err && <div className="settings-err">{err}</div>}

      <Section title="Memory">
        <Row label="Search and reference chats"
             desc="Let the agent search your past chats mid-conversation (local, read-only) when you reference earlier discussions.">
          <Toggle label="Search and reference chats" on={memorySearch}
                  onChange={(v) => save({ memory_search: v })} />
        </Row>
        <Row label="Generate memory from chat history" badge="Legacy"
             desc="Allow Claude to remember relevant context from your chats." locked>
          <Toggle label="Generate memory from chat history" on={false} disabled />
        </Row>
        <Row label="View and manage memory"
             desc="The agent's memory tool is available per-chat from the composer's + menu." locked>
          <LockedButton>Manage</LockedButton>
        </Row>
      </Section>

      <Section title="General">
        <Row label="Tool access mode" desc="Controls how connector tools are loaded in new conversations." locked>
          <InlineSelect label="Tool access mode" value="needed" disabled
                        options={[{ value: "needed", label: "Load tools when needed" }]} />
        </Row>
        <Row label="Connector search"
             desc="Let Claude search the connector directory and surface ones relevant to your conversation." locked>
          <Toggle label="Connector search" on={false} disabled />
        </Row>
        <Row label="Switch models when a message is flagged"
             desc="When safety measures flag a message, automatically switch to a different model to keep chatting." locked>
          <Toggle label="Switch models when a message is flagged" on={false} disabled />
        </Row>
      </Section>

      <Section title="Web search">
        <Row label="Search backend"
             desc="SearXNG is self-hosted and privacy-respecting; DuckDuckGo needs no setup.">
          <InlineSelect
            label="Search backend"
            value={searchProvider}
            options={[
              { value: "ddg", label: "DuckDuckGo (keyless)" },
              { value: "searxng", label: "SearXNG (self-hosted)" },
            ]}
            onChange={(v) => save({ search_provider: v })}
          />
        </Row>
        {searchProvider === "searxng" && (
          <Row label="SearXNG base URL" stacked>
            <input
              className="set-input wide"
              placeholder="http://localhost:8888"
              aria-label="SearXNG base URL"
              value={searxngUrl}
              onChange={(e) => set({ searxng_url: e.target.value })}
              onBlur={() => save({ searxng_url: searxngUrl })}
            />
          </Row>
        )}
      </Section>

      <Section title="Visuals">
        <Row label="Artifacts"
             desc="Generate code, documents, and designs in a dedicated window alongside your conversation. Toggle per-chat from the composer's + menu."
             locked>
          <Toggle label="Artifacts" on disabled />
        </Row>
        <Row label="Inline visualizations"
             desc="Allow models to generate interactive visualizations, charts, and diagrams directly in the conversation."
             locked>
          <Toggle label="Inline visualizations" on disabled />
        </Row>
      </Section>

      <Section title="Code execution and file creation">
        <Row label="Execution engine"
             desc="Lets the agent actually run Python and produce files. Docker gives the strongest isolation; local mode runs in a confined workspace with CPU/memory/time limits.">
          <InlineSelect
            label="Execution engine"
            value={codeExecution}
            options={[
              { value: "auto", label: "Automatic (Docker → local)" },
              { value: "docker", label: "Docker only" },
              { value: "local", label: "This device" },
              { value: "off", label: "Off" },
            ]}
            onChange={(v) => save({ code_execution: v })}
          />
        </Row>
        <Row label="Allow network egress"
             desc="Give the sandbox network access to install packages and libraries. Monitor chats closely — this comes with security risks."
             locked>
          <Toggle label="Allow network egress" on={false} disabled />
        </Row>
        <Row label="Domain allowlist" desc="Choose which domains the sandbox can access." locked>
          <InlineSelect label="Domain allowlist" value="pkg" disabled
                        options={[{ value: "pkg", label: "Package managers only" }]} />
        </Row>
      </Section>

      <ObservabilitySection />

      <Section title="Approvals & autonomy">
        <Row label="Permission mode"
             desc="Controls how often the agent pauses for your approval. Autonomous runs tools (including code) without asking.">
          <InlineSelect
            label="Permission mode"
            value={permissionMode}
            options={[
              { value: "strict", label: "Approve every step" },
              { value: "ask", label: "Approve sensitive steps" },
              { value: "auto", label: "Autonomous" },
            ]}
            onChange={(v) => save({ permission_mode: v })}
          />
        </Row>
        <Row label="Pause all automations"
             desc="Emergency kill-switch. When on, scheduled automations don't run and new background (Cowork) tasks are refused; turning it on also cancels any background tasks already running. Your chats are unaffected.">
          <Toggle label="Pause all automations" on={autonomyPaused}
                  onChange={(v) => save({ autonomy_paused: v })} />
        </Row>
      </Section>
    </>
  );
}
