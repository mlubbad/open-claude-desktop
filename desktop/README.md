# Open Claude Desktop — client (TypeScript / React + Tauri)

The Phase 3 desktop client. It talks to the FastAPI backend over HTTP + SSE and
consumes the backend's frozen event vocabulary (`ocd_core/agent.py`), so the
streaming UX — thinking panels, per-token answer streaming, tool cards, HITL
approval prompts — is a faithful, framework-free port of the transcript state
machine. This will replace the Reflex `frontend/` (kept behind a flag until parity).

## Structure

```
desktop/
├─ src/
│  ├─ api/        events.ts (typed SSE vocabulary) · client.ts (REST + SSE + BYOK)
│  ├─ state/      transcript.ts (pure reducer, unit-tested) · useTranscript.ts (React binding)
│  ├─ components/ Message · Composer · ApprovalPrompt · Settings
│  ├─ App.tsx  main.tsx  styles.css
├─ src-tauri/     Tauri v2 desktop shell (WebView host)
└─ package.json  vite.config.ts  tsconfig.json
```

The heart is `src/state/transcript.ts` — a pure `applyEvent(state, event)` reducer
with no framework dependency, covered by `transcript.test.ts` (vitest). Any UI can
reuse it.

## Develop (web)

```bash
npm install
npm run test        # vitest — the transcript reducer
npm run typecheck   # tsc
npm run build       # vite production build
npm run dev         # http://localhost:1420 (proxies /api -> http://localhost:8000)
```

Run the backend separately (`uvicorn app.main:app` from `backend/`). Point the client
at a different backend with `VITE_API_BASE`.

## Desktop shell (Tauri v2)

```bash
npm run tauri dev     # native window hosting the client
npm run tauri build   # signed installers (macOS/Windows/Linux)
```

Building the shell needs the [Tauri v2 prerequisites](https://v2.tauri.app/start/prerequisites/)
(Rust + platform WebView libs — `webkit2gtk-4.1`/`libsoup-3.0`/`gtk3` on Linux) and app
icons (`npm run tauri icon <png>`). The Rust dependency graph is validated (`cargo fetch`);
a full build must run on a machine with those WebView libraries installed.

**Wired now** (`src-tauri/` + `src/platform.ts`): single-instance focus, a global
**summon hotkey** (`CmdOrControl+Shift+Space`), native **notifications** on
background completion, the **auto-updater** (GitHub Releases `latest.json` feed), the
`opener` and `os` plugins, and a CSP scoped to the local backend. `platform.ts`
detects the Tauri global and falls back to web behavior in a plain browser, so the
client runs identically either way.

**Shell features:** system tray (close-to-tray, toggleable in Settings → Desktop
app), OS-global summon hotkey, launch at login (autostart), single instance,
native notifications, and signed auto-update from the GitHub release feed
(Settings → Desktop app → Check for updates). **Remaining:** deep links
(`claude://`) and the screenshot/Quick-Entry overlay.

## Sidecars (ships the app without a system Python or Node)

Two self-contained binaries are bundled next to the app executable
(`tauri.conf.json` → `externalBin`); build/fetch them before `tauri build`:

```bash
pip install ./backend pyinstaller
bash desktop/scripts/build-backend-sidecar.sh   # → src-tauri/binaries/ocd-backend-<triple>
bash desktop/scripts/fetch-node-sidecar.sh      # → src-tauri/binaries/ocd-node-<triple>
```

The frozen FastAPI backend serves the app (verified: `/healthz`, `/providers`);
the pinned Node runtime lets `.mcpb` extensions that launch `node` run without a
system install — the shell hands its path to the backend as `OCD_NODE`. Because
`externalBin` entries must exist at compile time, a local `cargo check`/`tauri
dev` needs both files staged (a tiny stub is fine for `ocd-backend`; see
`src-tauri/binaries/README.md`). The release workflow
(`.github/workflows/release.yml`) stages both before building the app.

## Status (foundation slice)

Working + verified: streaming chat over SSE (thinking/answer/tools/sources), the
interactive HITL approval prompt, provider/BYOK settings against `/providers`, a
theme-aware original design, stop-generation. Next: conversation history &
persistence, projects/knowledge, artifacts side-panel, message edit/retry/branch,
keyboard shortcuts, and the Tauri shell features above.
