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
(Rust + platform WebView libs) and app icons (`npm run tauri icon <png>`). Later
phases wire the system tray, a global summon hotkey, the auto-updater, deep links,
OS-keychain secret storage, and the FastAPI backend as a bundled sidecar.

## Status (foundation slice)

Working + verified: streaming chat over SSE (thinking/answer/tools/sources), the
interactive HITL approval prompt, provider/BYOK settings against `/providers`, a
theme-aware original design, stop-generation. Next: conversation history &
persistence, projects/knowledge, artifacts side-panel, message edit/retry/branch,
keyboard shortcuts, and the Tauri shell features above.
