import { useEffect, useState } from "react";

import { type ProviderInfo, providers, settings as settingsApi, type UserProfile } from "../api/client";

// BYOK settings: list providers, store a key per provider (the key is never read
// back — only a has_key flag), and pick the active provider + model for the session.
export function Settings({
  active,
  onPick,
  onClose,
}: {
  active: { provider: string; model: string };
  onPick: (provider: string, model: string) => void;
  onClose: () => void;
}) {
  const [list, setList] = useState<ProviderInfo[]>([]);
  const [keyDraft, setKeyDraft] = useState<Record<string, string>>({});
  const [err, setErr] = useState<string | null>(null);
  const [profile, setProfile] = useState<UserProfile>({});

  async function refresh() {
    try {
      setList(await providers.list());
    } catch (e) {
      setErr(String(e));
    }
  }

  useEffect(() => {
    void refresh();
    settingsApi.get().then((s) => setProfile(s.profile ?? {})).catch(() => {});
  }, []);

  function saveProfile() {
    void settingsApi.save({ profile }).catch((e) => setErr(String(e)));
  }

  function setField(k: keyof UserProfile, v: string) {
    setProfile((p) => ({ ...p, [k]: v }));
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
    <div className="settings-overlay" onClick={onClose}>
      <div className="settings" onClick={(e) => e.stopPropagation()}>
        <div className="settings-head">
          <h2>Providers &amp; models</h2>
          <button onClick={onClose}>✕</button>
        </div>
        {err && <div className="settings-err">{err}</div>}

        <label className="field-label">About you (personalizes every chat)</label>
        <div className="profile-form">
          <input placeholder="What should the assistant call you?" value={profile.call_me ?? ""}
                 onChange={(e) => setField("call_me", e.target.value)} onBlur={saveProfile} />
          <input placeholder="Your role or work (optional)" value={profile.role ?? ""}
                 onChange={(e) => setField("role", e.target.value)} onBlur={saveProfile} />
          <textarea placeholder="Response preferences (tone, length, format…)" rows={2}
                    value={profile.preferences ?? ""}
                    onChange={(e) => setField("preferences", e.target.value)} onBlur={saveProfile} />
        </div>

        <label className="field-label">Providers &amp; models</label>
        <ul className="provider-list">
          {list.map((p) => (
            <li key={p.id} className={p.id === active.provider ? "active" : ""}>
              <div className="provider-row">
                <span className="provider-label">
                  {p.label} {p.is_local && <em>(local)</em>}
                </span>
                <span className={`key-badge ${p.has_key ? "ok" : "missing"}`}>
                  {p.requires_key ? (p.has_key ? "key set" : "no key") : "no key needed"}
                </span>
              </div>
              {p.requires_key && (
                <div className="key-entry">
                  <input
                    type="password"
                    placeholder={`${p.label} API key`}
                    value={keyDraft[p.id] ?? ""}
                    onChange={(e) => setKeyDraft((d) => ({ ...d, [p.id]: e.target.value }))}
                  />
                  <button onClick={() => saveKey(p.id)} disabled={!(keyDraft[p.id] ?? "").trim()}>
                    Save
                  </button>
                </div>
              )}
              <div className="model-row">
                {(p.models.length ? p.models : [p.default_model].filter(Boolean)).map((m) => (
                  <button
                    key={m}
                    className={p.id === active.provider && m === active.model ? "model active" : "model"}
                    onClick={() => onPick(p.id, m)}
                    disabled={p.requires_key && !p.has_key}
                  >
                    {m}
                  </button>
                ))}
              </div>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}
