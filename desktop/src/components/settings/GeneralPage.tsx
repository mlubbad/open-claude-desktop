import { useState } from "react";

import type { UserProfile } from "../../api/client";
import type { ThemePref } from "../../state/theme";
import { type ChatFont, FONT_OPTIONS, getChatFont, getMotion, type MotionPref, setChatFont, setMotion } from "../../state/uiPrefs";
import { useSettingsFields } from "../../state/useSettingsFields";
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
// Layout mirrors Claude Desktop's General page; Voice renders faithfully but
// disabled — there is no voice backend in this build.
export function GeneralPage({ theme }: { theme: { pref: ThemePref; set: (p: ThemePref) => void } }) {
  const { values, set, save, err } = useSettingsFields();
  const [font, setFont] = useState<ChatFont>(getChatFont);
  const [motion, setMotionState] = useState<MotionPref>(getMotion);

  const profile: UserProfile = values?.profile ?? {};
  const setField = (k: keyof UserProfile, v: string) => set({ profile: { ...profile, [k]: v } });
  const saveProfile = () => save({ profile });

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
                 onChange={(e) => setField("name", e.target.value)} onBlur={saveProfile} />
        </Row>
        <Row label="What should VersoWork call you?">
          <input className="set-input" aria-label="What should VersoWork call you?" value={profile.call_me ?? ""}
                 onChange={(e) => setField("call_me", e.target.value)} onBlur={saveProfile} />
        </Row>
        <Row label="What best describes your work?">
          <InlineSelect
            label="What best describes your work?"
            value={workValue}
            options={[{ value: "", label: "Select…" }, ...WORK_OPTIONS.map((w) => ({ value: w, label: w }))]}
            onChange={(v) => save({ profile: { ...profile, role: v } })}
          />
        </Row>
        <Row
          stacked
          label="Custom instructions"
          desc="Applied across your chats and Cowork sessions."
        >
          <textarea
            className="set-textarea"
            aria-label="Custom instructions"
            rows={6}
            placeholder="Tone, format, standing instructions…"
            value={profile.preferences ?? ""}
            onChange={(e) => setField("preferences", e.target.value)}
            onBlur={saveProfile}
          />
        </Row>
      </Section>

      <Section title="Preferences">
        <Row label="Appearance" desc="Editorial light/dark or Apple-style Liquid Glass.">
          <Segmented<ThemePref>
            label="Appearance"
            value={theme.pref}
            onChange={theme.set}
            options={[
              { value: "system", label: <><Icon name="half" size={13} /><span>Auto</span></>, title: "System" },
              { value: "light", label: <><Icon name="sun" size={13} /><span>Light</span></>, title: "Light" },
              { value: "dark", label: <><Icon name="moon" size={13} /><span>Dark</span></>, title: "Dark" },
              { value: "glass", label: <><Icon name="glass" size={13} /><span>Glass</span></>, title: "Liquid Glass" },
              { value: "glass-dark", label: <><Icon name="glass-dark" size={13} /><span>Dark Glass</span></>, title: "Liquid Glass Dark" },
            ]}
          />
        </Row>
        <Row label="Chat font">
          <InlineSelect
            label="Chat font"
            value={font}
            options={FONT_OPTIONS.map((o) => ({ value: o.value, label: o.label }))}
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
