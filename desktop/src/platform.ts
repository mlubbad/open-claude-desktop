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

interface TauriGlobal {
  globalShortcut?: TauriGlobalShortcut;
  notification?: TauriNotification;
  event?: TauriEvent;
  opener?: TauriOpener;
  shell?: TauriOpener;
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
