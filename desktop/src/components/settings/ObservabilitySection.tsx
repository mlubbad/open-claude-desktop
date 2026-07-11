import { useEffect, useState } from "react";

import { observability as obsApi, type ObservabilityStatus, settings as settingsApi } from "../../api/client";
import { Row, Section, Segmented, Toggle } from "./controls";

// Observability (Opik): opt-in tracing of agent turns, with a Self-hosted vs Opik
// Cloud switch. Non-secret config (enabled/mode/url/project/workspace) is saved to
// settings; the Cloud API key is written to the OS keychain via a separate endpoint
// and never round-trips to the UI — only a "saved ✓" state (has_key).
export function ObservabilitySection() {
  const [st, setSt] = useState<ObservabilityStatus | null>(null);
  const [url, setUrl] = useState("");
  const [project, setProject] = useState("");
  const [workspace, setWorkspace] = useState("");
  const [keyInput, setKeyInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    obsApi
      .get()
      .then((s) => {
        setSt(s);
        setUrl(s.url);
        setProject(s.project);
        setWorkspace(s.workspace);
      })
      .catch((e) => setErr(String(e)));
  }, []);

  if (!st) return <Section title="Observability (Opik)"><Row label="Loading…" /></Section>;

  function patch(next: Partial<ObservabilityStatus>) {
    setSt((s) => (s ? { ...s, ...next } : s));
  }
  function saveConfig(fields: {
    opik_enabled?: boolean;
    opik_mode?: string;
    opik_url?: string;
    opik_project?: string;
    opik_workspace?: string;
  }) {
    void settingsApi.save(fields).catch((e) => setErr(String(e)));
  }

  async function saveKey() {
    if (!keyInput.trim()) return;
    setBusy(true);
    try {
      const r = await obsApi.setKey(keyInput.trim());
      patch({ has_key: r.has_key });
      setKeyInput("");
    } catch (e) {
      setErr(String(e));
    } finally {
      setBusy(false);
    }
  }
  async function clearKey() {
    setBusy(true);
    try {
      const r = await obsApi.clearKey();
      patch({ has_key: r.has_key });
    } catch (e) {
      setErr(String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Section title="Observability (Opik)">
      {err && <div className="settings-err">{err}</div>}
      <Row
        label="Trace agent turns"
        desc="Mirror every turn into an Opik trace (tool spans, thinking phases, usage). Opik is free and open-source — self-host it, or use Opik Cloud."
      >
        <Toggle
          label="Trace agent turns"
          on={st.enabled}
          onChange={(v) => {
            patch({ enabled: v });
            saveConfig({ opik_enabled: v });
          }}
        />
      </Row>

      {st.enabled && !st.sdk_installed && (
        <p className="settings-hint">
          The <code>opik</code> package isn't installed in the backend — run{" "}
          <code>pip install -e backend[observability]</code> and restart the app.
        </p>
      )}

      {st.enabled && (
        <>
          <Row label="Deployment" desc="Where traces are sent.">
            <Segmented
              label="Opik deployment"
              value={st.mode}
              onChange={(m) => {
                patch({ mode: m });
                saveConfig({ opik_mode: m });
              }}
              options={[
                { value: "local", label: "Self-hosted" },
                { value: "cloud", label: "Opik Cloud" },
              ]}
            />
          </Row>

          {st.mode === "local" ? (
            <Row label="Opik URL" desc="Your self-hosted instance, e.g. http://localhost:5173/api/" stacked>
              <input
                className="set-input wide"
                placeholder="http://localhost:5173/api/"
                aria-label="Opik URL"
                value={url}
                onChange={(e) => setUrl(e.target.value)}
                onBlur={() => saveConfig({ opik_url: url })}
              />
            </Row>
          ) : (
            <>
              <Row
                label="API key"
                desc="From comet.com → API keys. Stored in your OS keychain, never in settings."
                stacked
              >
                {st.has_key ? (
                  <div className="set-key-saved">
                    <span className="set-key-badge">Key saved ✓</span>
                    <button className="set-btn" disabled={busy} onClick={() => void clearKey()}>
                      {busy ? "…" : "Remove"}
                    </button>
                  </div>
                ) : (
                  <div className="set-key-row">
                    <input
                      className="set-input wide"
                      type="password"
                      placeholder="Opik Cloud API key"
                      aria-label="Opik Cloud API key"
                      value={keyInput}
                      onChange={(e) => setKeyInput(e.target.value)}
                    />
                    <button className="set-btn primary" disabled={busy || !keyInput.trim()} onClick={() => void saveKey()}>
                      {busy ? "Saving…" : "Save key"}
                    </button>
                  </div>
                )}
              </Row>
              <Row label="Workspace" desc="Your Comet workspace (defaults to your account's default)." stacked>
                <input
                  className="set-input wide"
                  placeholder="my-workspace"
                  aria-label="Opik workspace"
                  value={workspace}
                  onChange={(e) => setWorkspace(e.target.value)}
                  onBlur={() => saveConfig({ opik_workspace: workspace })}
                />
              </Row>
            </>
          )}

          <Row label="Project name" stacked>
            <input
              className="set-input wide"
              placeholder="open-claude-desktop"
              aria-label="Opik project name"
              value={project}
              onChange={(e) => setProject(e.target.value)}
              onBlur={() => saveConfig({ opik_project: project })}
            />
          </Row>
        </>
      )}
    </Section>
  );
}
