import { useEffect, useState } from "react";

import { settings as settingsApi } from "../../api/client";

// Capabilities: web-search backend, code-execution mode, and approval autonomy.
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
