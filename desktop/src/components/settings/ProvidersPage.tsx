import { useEffect, useState } from "react";

import { type ProviderInfo, providers, settings as settingsApi } from "../../api/client";
import { pickerModels } from "../../state/modelMeta";
import { Icon } from "../Icon";

// Models & keys: BYOK providers, connection test, and per-model picker visibility.
export function ProvidersPage({
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
