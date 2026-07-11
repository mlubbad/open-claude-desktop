import { useEffect, useState } from "react";

import { settings as settingsApi, type UserProfile } from "../../api/client";
import { type ChatFont, getChatFont, getMotion, type MotionPref, setChatFont, setMotion } from "../../state/uiPrefs";
import type { ThemePref } from "../../state/theme";
import { Icon } from "../Icon";
import { InlineSelect, Row, Section, Segmented } from "./controls";

const WORK_OPTIONS = [
  "Product management", "Engineering", "Human resources", "Marketing", "Writer",
  "Educator", "Consultant", "Researcher", "Software engineer", "Other",
];

function initials(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  if (parts.length === 0) return "?";
  return ((parts[0][0] ?? "") + (parts[parts.length - 1]?.[0] ?? "")).toUpperCase();
}

// General: profile (injected into every chat's system prompt) + app preferences.
// Layout mirrors Claude Desktop's General page; Voice + Notifications render
// faithfully but disabled — there is no voice/notification backend in this build.
export function GeneralPage({ theme }: { theme: { pref: ThemePref; set: (p: ThemePref) => void } }) {
  const [profile, setProfile] = useState<UserProfile>({});
  const [font, setFont] = useState<ChatFont>(getChatFont);
  const [motion, setMotionState] = useState<MotionPref>(getMotion);
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

  const workValue = WORK_OPTIONS.includes(profile.role ?? "") ? (profile.role as string) : profile.role ? "Other" : "";

  return (
    <>
      {err && <div className="settings-err">{err}</div>}

      <Section title="Profile">
        <Row label="Avatar">
          <span className="set-avatar" aria-label="Avatar initials">{initials(profile.name ?? profile.call_me ?? "")}</span>
        </Row>
        <Row label="Full name">
          <input className="set-input" aria-label="Full name" value={profile.name ?? ""}
                 onChange={(e) => setField("name", e.target.value)} onBlur={save} />
        </Row>
        <Row label="What should Claude call you?">
          <input className="set-input" aria-label="What should Claude call you?" value={profile.call_me ?? ""}
                 onChange={(e) => setField("call_me", e.target.value)} onBlur={save} />
        </Row>
        <Row label="What best describes your work?">
          <InlineSelect
            label="What best describes your work?"
            value={workValue}
            options={[{ value: "", label: "Select…" }, ...WORK_OPTIONS.map((w) => ({ value: w, label: w }))]}
            onChange={(v) => {
              setField("role", v);
              void settingsApi.save({ profile: { ...profile, role: v } }).catch((e) => setErr(String(e)));
            }}
          />
        </Row>
        <Row
          stacked
          label="Instructions for Claude"
          desc="Claude will keep these in mind across chats and Cowork."
        >
          <textarea
            className="set-textarea"
            aria-label="Instructions for Claude"
            rows={6}
            placeholder="Tone, format, standing instructions…"
            value={profile.preferences ?? ""}
            onChange={(e) => setField("preferences", e.target.value)}
            onBlur={save}
          />
        </Row>
      </Section>

      <Section title="Preferences">
        <Row label="Appearance">
          <Segmented<ThemePref>
            label="Appearance"
            value={theme.pref}
            onChange={theme.set}
            options={[
              { value: "system", label: <Icon name="half" size={14} />, title: "System" },
              { value: "light", label: <Icon name="sun" size={14} />, title: "Light" },
              { value: "dark", label: <Icon name="moon" size={14} />, title: "Dark" },
            ]}
          />
        </Row>
        <Row label="Chat font">
          <InlineSelect
            label="Chat font"
            value={font}
            options={[
              { value: "serif", label: "Serif" },
              { value: "sans", label: "System Sans" },
            ]}
            onChange={(v) => {
              const f = v as ChatFont;
              setFont(f);
              setChatFont(f);
            }}
          />
        </Row>
        <Row label="Motion" desc="Reduce animation in streaming responses and other interface elements.">
          <Segmented<MotionPref>
            label="Motion"
            value={motion}
            onChange={(m) => {
              setMotionState(m);
              setMotion(m);
            }}
            options={[
              { value: "system", label: "System" },
              { value: "reduced", label: "Reduced" },
            ]}
          />
        </Row>
      </Section>

      <Section title="Voice">
        <Row label="Language" locked>
          <InlineSelect label="Voice language" value="en" disabled options={[{ value: "en", label: "English" }]} />
        </Row>
        <Row label="Style" locked>
          <InlineSelect label="Voice style" value="buttery" disabled options={[{ value: "buttery", label: "Buttery" }]} />
        </Row>
        <Row label="Speed" locked>
          <InlineSelect label="Voice speed" value="normal" disabled options={[{ value: "normal", label: "Normal" }]} />
        </Row>
      </Section>
    </>
  );
}
