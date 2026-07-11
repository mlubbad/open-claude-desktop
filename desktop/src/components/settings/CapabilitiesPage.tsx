import { useEffect, useState } from "react";

import { settings as settingsApi } from "../../api/client";
import { InlineSelect, LockedButton, Row, Section, Toggle } from "./controls";
import { ObservabilitySection } from "./ObservabilitySection";

// Capabilities, structured like Claude Desktop's page (Memory / General / Visuals /
// Code execution). Real controls: web-search backend, code-execution engine, and the
// approvals/autonomy mode. Everything without a backend renders disabled — memory
// toggles, tool-access mode, artifact master switches (those are per-chat via the
// composer's + menu), and network-egress allowlists.
export function CapabilitiesPage() {
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

      <Section title="Memory">
        <Row label="Search and reference chats"
             desc="Allow Claude to search for relevant details in past chats." locked>
          <Toggle label="Search and reference chats" on={false} disabled />
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
            onChange={(v) => {
              setSearchProvider(v);
              save({ search_provider: v });
            }}
          />
        </Row>
        {searchProvider === "searxng" && (
          <Row label="SearXNG base URL" stacked>
            <input
              className="set-input wide"
              placeholder="http://localhost:8888"
              aria-label="SearXNG base URL"
              value={searxngUrl}
              onChange={(e) => setSearxngUrl(e.target.value)}
              onBlur={() => save({})}
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
             desc="Allow Claude to generate interactive visualizations, charts, and diagrams directly in the conversation."
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
            onChange={(v) => {
              setCodeExecution(v);
              save({ code_execution: v });
            }}
          />
        </Row>
        <Row label="Allow network egress"
             desc="Give Claude network access to install packages and libraries. Monitor chats closely — this comes with security risks."
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
            onChange={(v) => {
              setPermissionMode(v);
              save({ permission_mode: v });
            }}
          />
        </Row>
      </Section>
    </>
  );
}
