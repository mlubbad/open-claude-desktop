// Desktop app → General (P1-9): LIVE controls for the desktop shell — the OS-global
// summon hotkey, close-to-tray, launch at login, and auto-update. In a plain browser
// the switches render disabled with a note (there is no shell to obey them); the
// Computer-use section stays locked like the other not-in-this-build pages.

import { useEffect, useState } from "react";

import {
  checkForUpdate,
  getAppVersion,
  installUpdate,
  isLaunchAtLogin,
  isTauri,
  setLaunchAtLogin,
  type UpdateCheck,
} from "../../platform";
import { type DesktopPrefs, loadDesktopPrefs, saveDesktopPrefs } from "../../state/desktopPrefs";
import { IS_MAC } from "../../state/shortcuts";
import { LockedButton, Row, Section, Toggle } from "./controls";

export function DesktopGeneralPage() {
  const desktop = isTauri();
  const [prefs, setPrefs] = useState<DesktopPrefs>(loadDesktopPrefs);
  // Launch-at-login reads the OS autostart entry itself; null = unknown/unavailable.
  const [login, setLogin] = useState<boolean | null>(null);
  const [version, setVersion] = useState<string | null>(null);
  const [update, setUpdate] = useState<UpdateCheck | null>(null); // null = not checked
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    void isLaunchAtLogin().then(setLogin);
    void getAppVersion().then(setVersion);
  }, []);

  // Persisting fires the desktop-prefs change event; App applies the hotkey / tells
  // the shell about close-to-tray (single source of truth in state/desktopPrefs).
  const setPref = (patch: Partial<DesktopPrefs>) =>
    setPrefs((p) => {
      const next = { ...p, ...patch };
      saveDesktopPrefs(next);
      return next;
    });

  const toggleLogin = async (on: boolean) => {
    if (await setLaunchAtLogin(on)) setLogin(on);
  };

  const onCheck = async () => {
    setBusy(true);
    try {
      setUpdate(await checkForUpdate());
    } finally {
      setBusy(false);
    }
  };

  const onInstall = async () => {
    setBusy(true);
    if (!(await installUpdate())) {
      setUpdate({ status: "error", message: "install failed — try again, or download the release manually" });
    }
    setBusy(false);
  };

  const updateDesc =
    update === null
      ? `${version ? `Version ${version} — u` : "U"}pdates install from the project's signed GitHub release feed.`
      : update.status === "current"
        ? "You're on the latest version."
        : update.status === "unavailable"
          ? "Auto-update isn't available in this run (web or dev build)."
          : update.status === "error"
            ? `Update check failed: ${update.message}`
            : update.notes
              ? `v${update.version} — ${update.notes}`
              : `v${update.version} is ready to install.`;

  return (
    <>
      {!desktop && (
        <p className="settings-hint set-page-note">
          These switches control the desktop shell — open the desktop app to change them.
        </p>
      )}
      <Section title="App">
        <Row
          label="Quickly open Claude from anywhere"
          desc={
            <>
              <kbd className="set-kbd">{IS_MAC ? "⌘⇧Space" : "Ctrl+Shift+Space"}</kbd> summons the app
              and starts a new chat.
            </>
          }
        >
          <Toggle
            label="Quickly open Claude from anywhere"
            on={prefs.summonHotkey}
            disabled={!desktop}
            onChange={(v) => setPref({ summonHotkey: v })}
          />
        </Row>
        <Row label="System tray" desc="Closing the window keeps Claude running in the system tray.">
          <Toggle
            label="System tray"
            on={prefs.closeToTray}
            disabled={!desktop}
            onChange={(v) => setPref({ closeToTray: v })}
          />
        </Row>
        <Row label="Launch at login" desc="Start Claude automatically when you sign in to this computer.">
          <Toggle
            label="Launch at login"
            on={login === true}
            disabled={!desktop || login === null}
            onChange={(v) => void toggleLogin(v)}
          />
        </Row>
        <Row
          label="Keep computer awake"
          desc="Prevent your computer from idle-sleeping while Claude is open so scheduled tasks can run."
          locked
        >
          <Toggle label="Keep computer awake" on={false} disabled />
        </Row>
      </Section>
      <Section title="Updates">
        <Row label="App updates" desc={updateDesc}>
          {update?.status === "available" ? (
            <button className="set-btn" disabled={busy} onClick={() => void onInstall()}>
              {busy ? "Installing…" : `Restart & install v${update.version}`}
            </button>
          ) : (
            <button
              className="set-btn"
              disabled={!desktop || busy}
              title={!desktop ? "Open the desktop app to update" : undefined}
              onClick={() => void onCheck()}
            >
              {busy ? "Checking…" : "Check for updates"}
            </button>
          )}
        </Row>
      </Section>
      <Section title="Computer use">
        <Row
          label="Enable computer use"
          badge="Beta"
          desc="Let Claude take screenshots and control your keyboard and mouse in apps you allow."
          locked
        >
          <Toggle label="Enable computer use" on={false} disabled />
        </Row>
        <Row
          label="Denied apps"
          desc="Any request Claude makes to access these apps is automatically rejected."
          locked
        >
          <LockedButton>Add app</LockedButton>
        </Row>
        <Row label="Accessibility" locked>
          <span className="set-muted">Not supported</span>
        </Row>
        <Row label="Screen recording" locked>
          <span className="set-muted">Not supported</span>
        </Row>
      </Section>
    </>
  );
}
