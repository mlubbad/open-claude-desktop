// Save-to-Google-Drive, BYOK style: the user supplies their OWN Google OAuth
// Client ID (stored locally, never sent to our backend), the browser runs Google
// Identity Services' token flow, and the file is uploaded straight from the client
// to the Drive API with the drive.file scope (access only to files this app creates).
//
// No secrets, no server round-trip, no third-party service of ours in the middle —
// consistent with the app's bring-your-own-key model.

const CLIENT_ID_KEY = "ocd.gdriveClientId";
const GSI_SRC = "https://accounts.google.com/gsi/client";
const SCOPE = "https://www.googleapis.com/auth/drive.file";

export function getDriveClientId(): string {
  try {
    return localStorage.getItem(CLIENT_ID_KEY) ?? "";
  } catch {
    return "";
  }
}

export function setDriveClientId(id: string): void {
  try {
    if (id.trim()) localStorage.setItem(CLIENT_ID_KEY, id.trim());
    else localStorage.removeItem(CLIENT_ID_KEY);
  } catch {
    /* storage unavailable */
  }
}

interface TokenClient {
  requestAccessToken: (opts?: { prompt?: string }) => void;
}
interface GsiOauth2 {
  initTokenClient: (cfg: {
    client_id: string;
    scope: string;
    callback: (resp: { access_token?: string; error?: string }) => void;
    error_callback?: (err: { type?: string; message?: string }) => void;
  }) => TokenClient;
}

declare global {
  interface Window {
    google?: { accounts?: { oauth2?: GsiOauth2 } };
  }
}

let gsiLoading: Promise<void> | null = null;

function loadGsi(): Promise<void> {
  if (window.google?.accounts?.oauth2) return Promise.resolve();
  if (!gsiLoading) {
    gsiLoading = new Promise<void>((resolve, reject) => {
      const s = document.createElement("script");
      s.src = GSI_SRC;
      s.async = true;
      s.onload = () => resolve();
      s.onerror = () => {
        gsiLoading = null;
        reject(new Error("Couldn't load Google's sign-in library (offline or blocked)."));
      };
      document.head.appendChild(s);
    });
  }
  return gsiLoading;
}

function getToken(clientId: string): Promise<string> {
  return loadGsi().then(
    () =>
      new Promise<string>((resolve, reject) => {
        const oauth2 = window.google?.accounts?.oauth2;
        if (!oauth2) {
          reject(new Error("Google sign-in library unavailable."));
          return;
        }
        const client = oauth2.initTokenClient({
          client_id: clientId,
          scope: SCOPE,
          callback: (resp) => {
            if (resp.access_token) resolve(resp.access_token);
            else reject(new Error(resp.error || "Google authorization was cancelled."));
          },
          error_callback: (err) =>
            reject(new Error(err?.message || err?.type || "Google authorization failed.")),
        });
        client.requestAccessToken();
      }),
  );
}

// Upload one file to the user's Drive; resolves with a link to open it.
export async function saveToDrive(opts: {
  clientId: string;
  name: string;
  mimeType: string;
  content: string;
}): Promise<{ id: string; link: string }> {
  const token = await getToken(opts.clientId);
  const boundary = "ocd-drive-" + Math.random().toString(36).slice(2);
  const body =
    `--${boundary}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n` +
    JSON.stringify({ name: opts.name, mimeType: opts.mimeType }) +
    `\r\n--${boundary}\r\nContent-Type: ${opts.mimeType}\r\n\r\n` +
    opts.content +
    `\r\n--${boundary}--`;
  const resp = await fetch(
    "https://www.googleapis.com/upload/drive/v3/files?uploadType=multipart&fields=id",
    {
      method: "POST",
      headers: {
        Authorization: `Bearer ${token}`,
        "Content-Type": `multipart/related; boundary=${boundary}`,
      },
      body,
    },
  );
  if (!resp.ok) {
    const detail = await resp.text().catch(() => "");
    throw new Error(`Drive upload failed (${resp.status}): ${detail.slice(0, 200)}`);
  }
  const data = (await resp.json()) as { id: string };
  return { id: data.id, link: `https://drive.google.com/file/d/${data.id}/view` };
}
