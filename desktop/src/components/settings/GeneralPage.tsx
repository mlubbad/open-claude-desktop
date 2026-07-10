import { useEffect, useState } from "react";

import { settings as settingsApi, type UserProfile } from "../../api/client";

// General: the user profile injected into every chat's system prompt.
export function GeneralPage() {
  const [profile, setProfile] = useState<UserProfile>({});
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    settingsApi
      .get()
      .then((s) => setProfile(s.profile ?? {}))
      .catch(() => {});
  }, []);

  function save() {
    void settingsApi.save({ profile }).catch((e) => setErr(String(e)));
  }
  function setField(k: keyof UserProfile, v: string) {
    setProfile((p) => ({ ...p, [k]: v }));
  }

  return (
    <>
      {err && <div className="settings-err">{err}</div>}
      <p className="settings-hint">Personalizes every chat — injected into the system prompt.</p>
      <div className="profile-form">
        <label className="field-label" htmlFor="pf-name">What should the assistant call you?</label>
        <input id="pf-name" value={profile.call_me ?? ""}
               onChange={(e) => setField("call_me", e.target.value)} onBlur={save} />
        <label className="field-label" htmlFor="pf-role">Your role or work (optional)</label>
        <input id="pf-role" value={profile.role ?? ""}
               onChange={(e) => setField("role", e.target.value)} onBlur={save} />
        <label className="field-label" htmlFor="pf-prefs">Response preferences</label>
        <textarea id="pf-prefs" rows={3} placeholder="Tone, length, format…"
                  value={profile.preferences ?? ""}
                  onChange={(e) => setField("preferences", e.target.value)} onBlur={save} />
      </div>
    </>
  );
}
