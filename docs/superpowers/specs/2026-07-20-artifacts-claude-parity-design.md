# Artifacts: Claude.ai parity + preview-failure fixes — Design

Date: 2026-07-20
Status: implemented in the same change series (autonomous session — the normal
"user reviews spec" gate could not run; deviations from this design are listed in the
plan's Deviations section).
Base: `origin/main` (a751a3c).

## 1. Context

The product already ships a deliberate Claude-Artifacts clone: `create_artifact` /
`update_artifact` function tools + live token-streaming over SSE
(`artifact_open/delta/close`), a side `ArtifactPanel` (preview/code tabs, versions,
Copy, Download, Print-as-PDF, Save-to-Drive, Add-to-project), sandboxed
`iframe[srcdoc]` previews, and code-execution "produced files" download cards.
Kinds: `html | react | svg | mermaid | code | markdown | csv`.

The user reported "some artifacts fail to preview", with a reproducible case: a
`mermaid` artifact (`xychart-beta`, Arabic labels) rendering mermaid's
"Syntax error in text — mermaid version 11.16.0" bomb screen.

### Root causes (empirically verified against live mermaid 11.16.0)

1. **Fenced content.** The exact failing chart parses AND renders fine in mermaid
   11.16.0 — Arabic labels, parentheses, `-->`, decimals, all of it. What breaks it is
   the model wrapping the artifact body in a ` ```mermaid … ``` ` markdown fence inside
   the tool-call `content` (visible verbatim in the user's copy of the artifact). Mermaid
   then reports "No diagram type detected", which renders as the same bomb screen.
   Nothing in the pipeline strips fences. This breaks any kind, not just mermaid
   (an `html` artifact wrapped in a fence shows the fence as literal text, a fenced
   `csv` corrupts the table header, …).
2. **React artifacts are doubly broken.** The srcdoc mounts `doc.content` directly as an
   ES module — raw JSX never parses in-browser — and its import map points at
   `esm.sh`, which the srcdoc CSP (`script-src … cdn.jsdelivr.net`) blocks. Every react
   preview fails today.
3. **Real mermaid lexer limitation (adjacent class).** `xychart` tokenizes unquoted text
   with an ASCII-only `ALPHA` rule: unquoted Arabic/CJK/accented labels (and stray
   Unicode bidi control characters outside quotes) throw "Unrecognized text" even
   though *quoted* labels are fine (mermaid-js/mermaid#7157, #7256; grammar:
   `xychart.jison`; verified on 11.16.0). Also: labels can never contain `"` — the
   grammar has no escape — and single-quoted strings are not strings.
4. **Packaged-app CSP gap (latent).** `tauri.conf.json` has no `script-src`, so
   `default-src 'self'` applies; `about:srcdoc` documents inherit the embedder's policy,
   so in the *packaged* app every CDN-based preview (mermaid today, react after this
   change) is blocked. Dev builds don't enforce it, which is why the screenshot shows
   mermaid actually loading.

### What Claude actually supports (deep-research summary, 2026-07-20)

- **Types** (Gen 1/2 MIME taxonomy): `application/vnd.ant.code` (+`language`),
  `text/markdown`, `text/html`, `image/svg+xml`, `application/vnd.ant.mermaid`,
  `application/vnd.ant.react`; renderer additionally understands
  `text/plain`/`text/csv`/`application/json`/`application/xml`. Gen 3 (current
  claude.ai) is file/extension-based and adds renderable **PDF**; `.docx`/`.xlsx`/
  `.pptx`/`.pdf` binaries belong to the separate **Create-files** feature (download
  cards, not the artifact panel) — which this app mirrors via code-execution
  produced-files.
- **Protocol**: Gen 1 `<antArtifact identifier type title language>` inline tags →
  Gen 2 an `artifacts` tool with `command: create | update | rewrite`, where `update`
  takes `old_str`/`new_str` and `old_str` "must appear EXACTLY once"; use `update` for
  <20 changed lines and <5 locations, `rewrite` otherwise. One artifact per message.
  Full, untruncated content on create/rewrite. Our `create_artifact`/`update_artifact`
  pair matches Gen 2 minus targeted updates.
- **Criteria**: artifact for substantial (>15–20 lines / >1500 chars), self-contained,
  reusable/iterable content; inline for snippets, explanations, one-offs.
- **React runtime**: default export required, no required props, Tailwind core utility
  classes, storage APIs banned, and a fixed library set (react, recharts,
  lucide-react, d3, lodash, papaparse, xlsx, mathjs, chart.js, tone, three r128,
  plotly, shadcn/ui). HTML artifacts: single file, external scripts from one
  allowlisted CDN.

## 2. Goals

1. Fix the reported preview failures for good: fence-wrapped content, broken react
   runtime, mermaid Unicode edge cases — with regression tests including the user's
   exact Arabic chart.
2. Close the protocol/prompt gaps vs Claude Gen 2: targeted `update_artifact`
   (`old_str`/`new_str`, exactly-once), and system-prompt artifact criteria that match
   Claude's (thresholds, one-per-message, no-fences, per-kind rules, truthful library
   roster).
3. Readable failure surfaces: a mermaid/react error shows the message and the source,
   never a bare bomb screen.
4. Make previews work in the packaged app (Tauri CSP), not only `vite dev`.

Non-goals (explicit follow-ups, §7): publish/share/remix, `window.claude.complete`,
`window.fs.readFile` bridge, shadcn/ui in the sandbox, LaTeX/Graphviz kinds, PDF *as an
artifact kind* (binary PDFs keep flowing through produced-files), Google-Docs/Sheets
conversion on Drive save.

## 3. Architecture

### 3.1 Content sanitization (backend ingestion + frontend render)

New pure helper `strip_code_fence(content)` in `backend/ocd_core/artifact_tools.py`,
applied in `create()` and `update()`:

- If the trimmed content is a single fenced block — first line ` ```lang? `, last line
  ` ``` ` — unwrap it (greedy to the *last* fence line, so inner fences in a markdown
  doc survive).
- Applied uniformly to every kind. Claude's own rule ("do not put Mermaid code in a
  code block") is enforced by construction rather than hoped for.

Frontend mirror `stripFence()` in a new pure module `desktop/src/state/artifactSrcdoc.ts`
(fed by the renderer), because (a) persisted transcripts already contain fenced
artifacts, (b) during live streaming the closing fence hasn't arrived yet — the
frontend variant also drops a *lone opening* fence line so the live preview doesn't
flash an error until `artifact_close`.

### 3.2 Preview srcdoc builder → `desktop/src/state/artifactSrcdoc.ts`

`buildSrcDoc` + `escapeHtml` move out of `ArtifactPanel.tsx` into a pure, unit-tested
module (repo convention: logic in `state/*.ts` with colocated vitest specs). Panel
behavior-neutral apart from the fixes below. All srcdoc scripts stay on
`cdn.jsdelivr.net` (single-CDN CSP), all versions pinned.

**Mermaid** — replace the `<pre class="mermaid">` + `startOnLoad` dance with an explicit
pipeline that never round-trips the source through HTML text:

```html
<script id="src" type="application/json">…JSON-embedded source…</script>
<script src="…/mermaid@11.16.0/dist/mermaid.min.js"></script>
<script>mermaid.render(id, src).then(inject svg).catch(show error card)</script>
```

- Source is `JSON.stringify`-embedded with `<` escaped as `<` (script-tag-safe).
- `normalizeMermaid()` strips zero-width/bidi control characters
  (`U+200B/200E/200F/202A–202E/2060–2069/FEFF`) — invisible characters that are fatal
  lexer errors outside quoted regions and no-ops visually.
- Pin `mermaid@11.16.0` (was floating `@11`).
- On error: a styled card with the mermaid message and the diagram source in a
  `<pre>` — the bomb screen dies here.

**React** — make the runtime real:

- Import map (all pinned, jsdelivr `+esm`): `react`, `react/jsx-runtime`,
  `react-dom`, `react-dom/client`, plus Claude's library roster where it has a working
  browser ESM build: `recharts`, `lucide-react@0.383.0` (current claude.ai pin),
  `d3`, `lodash` (+ `lodash-es`), `papaparse`, `xlsx`, `mathjs`, `chart.js`, `tone`,
  `three@0.128.0` (Claude's r128, matching its documented caveats). Entries are lazy —
  unimported libraries cost nothing.
- `@tailwindcss/browser@4` script so Tailwind utility classes work (superset of
  Claude's precompiled-core-classes rule; the prompt still teaches the core-classes
  habit for portability).
- `rewriteExports(src)` (pure TS, unit-tested) textually converts
  `export default …` / `export const|function|class …` into plain declarations bound to
  `__ARTIFACT_DEFAULT__` so the mount epilogue can render
  `__ARTIFACT_DEFAULT__ ?? App ?? Component`.
- In-iframe bootstrap: load `@babel/standalone` (pinned), transform the JSON-embedded
  source with `presets: [[react, {runtime:"automatic"}], [typescript, {isTSX:true}]]`
  (so both JSX and TSX artifacts run; automatic runtime resolves via the
  `react/jsx-runtime` import-map entry), then inject the result as a
  `<script type="module">` plus the mount epilogue. `window.onerror` + transform
  `catch` render the same error card as mermaid.

**HTML/SVG** — unchanged passthrough/wrapping (sandbox is the enforcement boundary);
the system prompt gains Claude-style guidance (single file; load external scripts from
cdnjs.cloudflare.com or cdn.jsdelivr.net; SVG: use `viewBox`, not width/height).
Deviation from Claude noted: we do not inject a CSP into model HTML, so any https CDN
works inside the sandbox — safe because the iframe stays `sandbox="allow-scripts"`
with an opaque origin, and stricter injection would break existing artifacts.

### 3.3 Targeted updates — Claude Gen 2 `update` semantics

`update_artifact` gains optional `old_str`/`new_str`:

- Exactly-once rule verbatim from Claude's contract: 0 matches → error "old_str not
  found"; >1 → error "appears N times — it must be unique"; errors return to the model
  as tool results so it can retry or fall back to full content.
- `content` remains supported and keeps meaning "full rewrite" (Claude's `rewrite`).
- Tool description teaches Claude's thresholds: targeted update for <20 lines / <5
  locations changed, full rewrite otherwise.
- Emission is unchanged: the backend computes the new full content, bumps `version`,
  and `_completion_events` streams `artifact_open + full delta + close` exactly as a
  full-content update does today (the live `ArtifactArgStream` path never opens for
  old_str updates since no `content` key arrives — already the correct behavior).

### 3.4 System prompt (`artifact_tools.system_prompt_section`)

Rewritten to Claude's Gen-2 criteria, adapted truthfully to this runtime:

- When to create (substantial >20 lines or >1500 chars, self-contained, iterable,
  for-use-outside-chat; must-use list) and when NOT to (snippets, explanations,
  one-offs). One artifact per message unless asked. Complete untruncated content;
  never fence the content.
- Per-kind rules: mermaid (raw source, no fence; **double-quote every xychart/pie
  label and title** — non-ASCII or parenthesized unquoted labels are lexer errors;
  labels cannot contain `"`), react (default export, no required props, Tailwind
  utilities, exact library roster with import examples, no storage APIs — the sandbox
  throws), html (single file, CDN guidance, no storage), svg (viewBox), code
  (+`language`), csv & produced-files paragraphs kept from today's prompt.
- Targeted-update guidance per §3.3.

### 3.5 Packaged-app CSP (`desktop/src-tauri/tauri.conf.json`)

Add `script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net` and
`font-src 'self' data: https:` to the Tauri CSP (srcdoc previews *inherit* the app
policy; they cannot loosen it from inside). Trade-off accepted and documented:
`'unsafe-inline'` weakens the main window's script policy; the clean fix is serving
previews from a dedicated Tauri custom protocol with its own headers — recorded as a
follow-up. `csp.test.ts` grows regression guards so the preview contract can't silently
break again.

### 3.6 Produced-files ("Create files" parity)

Already present end-to-end (code-execution → `files` SSE event → download cards; text
files also open as artifacts; `backend` declares the `files` extra with pandas /
openpyxl / python-docx / python-pptx / reportlab / Pillow / matplotlib). This change
only makes the system prompt advertise the xlsx/docx/pptx/pdf paths explicitly so
models reliably route "make me a spreadsheet/document/PDF" through code execution.

## 4. Testing

- **Backend (pytest)**: `strip_code_fence` unit matrix (fenced/unfenced/inner-fence/
  CRLF/no-trailing-newline/language tags); `create()` strips; `update()` strips;
  old_str exactly-once (applies / not-found / ambiguous); rewrite path; version bumps;
  tool-spec schema contains the new fields; system prompt mentions the new rules.
- **Frontend (vitest)**: `artifactSrcdoc` — stripFence (incl. streaming lone-fence),
  normalizeMermaid (bidi strip), JSON script-tag embedding (`</script>` safety),
  mermaid srcdoc contains pinned version + embedded source + no `<pre class="mermaid">`
  escaping path, react srcdoc contains import map pins + Babel + rewritten exports,
  `rewriteExports` matrix (default fn/class/arrow/identifier, named exports),
  **the exact user-reported Arabic xychart embeds intact**; existing
  `artifactExport`/panel tests keep passing; `csp.test.ts` additions.
- **Live verification**: serve the generated mermaid srcdoc for the Arabic chart over
  a local server in a real browser; assert the SVG renders (no bomb), screenshot.
  `npm run build` + `tsc -b --noEmit` + full `vitest run` + backend `pytest`.

## 5. Compatibility

- Wire contract unchanged (`artifact_open/delta/close` untouched; `events.ts` stable).
- Persisted transcripts: old fenced artifacts render correctly now (frontend strip);
  old clean artifacts unaffected (strip is a no-op).
- `update_artifact` remains backward-compatible (`content`-only calls behave as
  before).

## 6. Risks

- jsdelivr `+esm` builds of heavyweight libs (plotly especially) can be flaky →
  roster only includes verified-working entries; plotly is attempted but its absence
  degrades to the error card, and the prompt lists recharts first (matching Claude's
  own preference order). [Resolved during implementation: see plan Deviations for the
  final verified roster.]
- `'unsafe-inline'` in the app CSP (§3.5) — documented trade-off + follow-up.
- Babel-standalone is ~3 MB from CDN on first react preview — cached by the webview
  thereafter; acceptable for a desktop app.

## 7. Follow-ups (not in this change)

Custom Tauri protocol for previews (per-response CSP, no inherited policy);
`window.fs.readFile` bridge to project files; `window.claude.complete` proxied through
the backend; publish/share/remix; shadcn/ui bundling for the sandbox; Google
Docs/Sheets conversion on Drive save; optional `json`/`graphviz`/`latex` kinds.
