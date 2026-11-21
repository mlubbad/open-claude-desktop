// Platform integration: use native desktop capabilities when running inside the Tauri
// shell (via the global `window.__TAURI__`, enabled by withGlobalTauri), and fall back
// to web behavior otherwise. All functions are safe to call in a plain browser.

interface TauriGlobalShortcut {
  register(shortcut: string, handler: () => void): Promise<void>;
  unregister(shortcut: string): Promise<void>;
}

interface TauriNotification {
  isPermissionGranted(): Promise<boolean>;
  requestPermission(): Promise<"granted" | "denied" | "default">;
  sendNotification(options: { title: string; body?: string } | string): void;
}

interface TauriEvent {
  listen(event: string, handler: (e: unknown) => void): Promise<() => void>;
}

interface TauriOpener {
  openUrl?(url: string): Promise<void>;
  open?(path: string): Promise<void>;
}

interface TauriAutostart {
  enable(): Promise<void>;
  disable(): Promise<void>;
  isEnabled(): Promise<boolean>;
}

interface TauriUpdate {
  version: string;
  body?: string;
  available?: boolean;
  downloadAndInstall(onEvent?: (e: unknown) => void): Promise<void>;
}

interface TauriUpdater {
  check(): Promise<TauriUpdate | null>;
}

interface TauriProcess {
  relaunch(): Promise<void>;
}

interface TauriApp {
  getVersion(): Promise<string>;
}

interface TauriCore {
  invoke<T = unknown>(cmd: string, args?: Record<string, unknown>): Promise<T>;
}

interface TauriGlobal {
  globalShortcut?: TauriGlobalShortcut;
  notification?: TauriNotification;
  event?: TauriEvent;
  opener?: TauriOpener;
  shell?: TauriOpener;
  autostart?: TauriAutostart;
  updater?: TauriUpdater;
  process?: TauriProcess;
  app?: TauriApp;
  core?: TauriCore;
}

function tauri(): TauriGlobal | null {
  if (typeof window === "undefined") return null;
  const w = window as unknown as { __TAURI__?: TauriGlobal; __TAURI_INTERNALS__?: unknown };
  if (w.__TAURI__) return w.__TAURI__;
  // Present in Tauri even if the convenience global isn't populated yet.
  return "__TAURI_INTERNALS__" in w ? {} : null;
}

export function isTauri(): boolean {
  return tauri() !== null;
}

// Register an OS-global summon shortcut (desktop only). No-op in a browser, which
// cannot claim global hotkeys. Returns true if it was registered.
export async function registerSummonHotkey(accelerator: string, handler: () => void): Promise<boolean> {
  const t = tauri();
  if (!t?.globalShortcut) return false;
  try {
    await t.globalShortcut.register(accelerator, handler);
    return true;
  } catch {
    return false;
  }
}

export async function unregisterSummonHotkey(accelerator: string): Promise<void> {
  const t = tauri();
  if (!t?.globalShortcut) return;
  try {
    await t.globalShortcut.unregister(accelerator);
  } catch {
    /* ignore */
  }
}

// Listen for the tray's "New Chat" menu action (desktop only). Returns an unlisten
// function; a no-op unlisten in a browser. The Rust tray emits `tray://new-chat`.
export async function onTrayNewChat(handler: () => void): Promise<() => void> {
  const t = tauri();
  if (!t?.event) return () => {};
  try {
    return await t.event.listen("tray://new-chat", () => handler());
  } catch {
    return () => {};
  }
}

// Open a URL in the user's browser: the OS default browser via Tauri's opener/shell
// plugin on desktop, else a new browser tab. Used to send the user to an OAuth consent
// page (connector sign-in). Returns true if a handler accepted it.
export async function openExternal(url: string): Promise<boolean> {
  const t = tauri();
  const opener = t?.opener ?? t?.shell;
  if (opener?.openUrl) {
    try {
      await opener.openUrl(url);
      return true;
    } catch {
      /* fall through */
    }
  }
  if (opener?.open) {
    try {
      await opener.open(url);
      return true;
    } catch {
      /* fall through */
    }
  }
  if (typeof window !== "undefined") {
    const w = window.open(url, "_blank", "noopener,noreferrer");
    return w !== null;
  }
  return false;
}

// The desktop app's own version (from tauri.conf.json), or null on the web.
export async function getAppVersion(): Promise<string | null> {
  const t = tauri();
  if (!t?.app) return null;
  try {
    return await t.app.getVersion();
  } catch {
    return null;
  }
}

// Launch-at-login via the OS autostart entry (desktop only). isLaunchAtLogin
// returns null when the capability is unavailable (plain browser); setLaunchAtLogin
// returns whether the change took.
export async function isLaunchAtLogin(): Promise<boolean | null> {
  const t = tauri();
  if (!t?.autostart) return null;
  try {
    return await t.autostart.isEnabled();
  } catch {
    return null;
  }
}

export async function setLaunchAtLogin(on: boolean): Promise<boolean> {
  const t = tauri();
  if (!t?.autostart) return false;
  try {
    if (on) await t.autostart.enable();
    else await t.autostart.disable();
    return true;
  } catch {
    return false;
  }
}

// Tell the shell whether closing the window should hide it to the tray (true) or
// quit the app (false). No-op on the web.
export async function setCloseToTray(on: boolean): Promise<void> {
  const t = tauri();
  if (!t?.core) return;
  try {
    await t.core.invoke("set_close_to_tray", { enabled: on });
  } catch {
    /* ignore */
  }
}

// Auto-update (desktop only): check the signed release feed, then install.
export type UpdateCheck =
  | { status: "unavailable" } // web, or a dev build without the updater
  | { status: "current" }
  | { status: "available"; version: string; notes: string }
  | { status: "error"; message: string };

// The Update handle from the last successful check, kept so installUpdate() can
// download exactly what the user was shown.
let pendingUpdate: TauriUpdate | null = null;

export async function checkForUpdate(): Promise<UpdateCheck> {
  const t = tauri();
  if (!t?.updater) return { status: "unavailable" };
  try {
    const u = await t.updater.check();
    if (!u || u.available === false || !u.version) return { status: "current" };
    pendingUpdate = u;
    return { status: "available", version: u.version, notes: u.body ?? "" };
  } catch (e) {
    return { status: "error", message: String(e) };
  }
}

// Download + install the update found by checkForUpdate, then relaunch into the
// new build. Returns false when there is nothing pending or the install failed.
export async function installUpdate(): Promise<boolean> {
  if (!pendingUpdate) return false;
  try {
    await pendingUpdate.downloadAndInstall();
    pendingUpdate = null;
  } catch {
    return false;
  }
  try {
    // On Windows the installer exits the app itself; elsewhere we relaunch.
    await tauri()?.process?.relaunch();
  } catch {
    /* ignore */
  }
  return true;
}

// Fire a native notification (Tauri), else the Web Notification API, else no-op.
export async function notify(title: string, body?: string): Promise<void> {
  const t = tauri();
  if (t?.notification) {
    try {
      let granted = await t.notification.isPermissionGranted();
      if (!granted) granted = (await t.notification.requestPermission()) === "granted";
      if (granted) t.notification.sendNotification({ title, body });
      return;
    } catch {
      /* fall through to web */
    }
  }
  if (typeof Notification !== "undefined") {
    try {
      if (Notification.permission === "granted") {
        new Notification(title, { body });
      } else if (Notification.permission !== "denied") {
        const perm = await Notification.requestPermission();
        if (perm === "granted") new Notification(title, { body });
      }
    } catch {
      /* ignore */
    }
  }
}
