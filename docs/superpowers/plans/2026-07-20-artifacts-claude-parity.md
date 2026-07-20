# Artifacts Claude-Parity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> Authoring note (deviation from the writing-plans template): this plan was written and
> executed in the same autonomous session by the same agent, so steps carry the
> load-bearing code (regexes, schemas, pin lists, srcdoc skeletons) rather than every
> final line verbatim; the spec is
> `docs/superpowers/specs/2026-07-20-artifacts-claude-parity-design.md`.

**Goal:** Fix artifact preview failures (fenced content, broken react runtime, mermaid Unicode edges, packaged-app CSP) and close the protocol gaps vs Claude Gen 2 (targeted updates, artifact criteria in the system prompt).

**Architecture:** Sanitize content at both ends (backend ingestion `strip_code_fence`, frontend `stripFence`); move all srcdoc building into a pure, tested `desktop/src/state/artifactSrcdoc.ts` (mermaid via JSON-embedded `mermaid.render`, react via Babel-standalone + pinned jsdelivr import map); add `old_str`/`new_str` to `update_artifact` with Claude's exactly-once contract; rewrite the artifacts system-prompt section to Claude's criteria; extend the Tauri CSP so previews work packaged.

**Tech Stack:** FastAPI/pytest (backend), React 18 + Vite + vitest (desktop), mermaid@11.16.0, @babel/standalone, jsdelivr `+esm`, Tauri 2.

**Execution log convention:** tick checkboxes as tasks complete; record deviations in the final section.

---

### Task 1: Backend fence stripping

**Files:**
- Modify: `backend/ocd_core/artifact_tools.py`
- Test: `backend/tests/test_artifacts.py`

- [x] **Step 1.1: Failing tests** — in `test_artifacts.py` add `TestStripCodeFence` +
  create/update integration cases. Core matrix (function under test
  `artifact_tools.strip_code_fence`):
  - ` ```mermaid\nxychart-beta\n...\n``` ` → unwrapped body
  - ` ``` `-only fence (no language) unwraps; `~~~` fences NOT touched
  - unfenced content unchanged; fence *plus trailing prose* unchanged (not a single block)
  - markdown doc whose body contains an inner fence: outer strip keeps inner (greedy last-fence rule)
  - CRLF fenced content unwraps; missing trailing newline before closer unwraps
  - `create({"content": fenced})` stores stripped; `update` with fenced `content` stores stripped
- [x] **Step 1.2: Run; expect FAIL** — `python -m pytest backend/tests/test_artifacts.py -q` (AttributeError: strip_code_fence)
- [x] **Step 1.3: Implement** in `artifact_tools.py`:

```python
_FENCE_RE = re.compile(r"\A```[ \t]*[\w+.-]*[ \t]*\r?\n(.*)\r?\n?```[ \t]*\Z", re.S)

def strip_code_fence(content: str) -> str:
    m = _FENCE_RE.match(content.strip())
    return m.group(1) if m else content
```
  applied to `content` in `create()` and (when present) `update()`.
- [x] **Step 1.4: Run; expect PASS** (same command)
- [x] **Step 1.5: Commit** — `fix(artifacts): unwrap fenced tool-call content at ingestion`

### Task 2: `update_artifact` targeted edits (Claude `update` semantics)

**Files:**
- Modify: `backend/ocd_core/artifact_tools.py` (UPDATE_ARTIFACT_TOOL schema + `update()`)
- Test: `backend/tests/test_artifacts.py`

- [x] **Step 2.1: Failing tests** — old_str/new_str applies (version bumps, content replaced);
  old_str absent from doc → `(None, "old_str not found …")`; old_str appearing twice →
  error mentioning the count and uniqueness; old_str + content together → content (full
  rewrite) wins; schema lists `old_str`/`new_str` properties and `content` no longer in
  `required`; new_str containing a fence is NOT stripped (targeted replacement is literal).
- [x] **Step 2.2: Run; expect FAIL**
- [x] **Step 2.3: Implement** — in `update()`:

```python
if not args.get("content") and args.get("old_str") is not None:
    old, new = args["old_str"], args.get("new_str") or ""
    n = doc["content"].count(old)
    if n == 0:  return None, f"old_str not found in artifact '{aid}'. Send the exact text (or the full content)."
    if n > 1:   return None, f"old_str appears {n} times in artifact '{aid}' — it must be unique. Include more surrounding context."
    doc["content"] = doc["content"].replace(old, new, 1)
elif args.get("content"): ...  # existing full-content path (+ strip_code_fence)
```
  Schema: add `old_str`/`new_str` string properties; `required: ["id"]`; description
  teaches "targeted update for <20 changed lines and <5 locations; otherwise send full
  content"; old_str "must appear exactly once".
- [x] **Step 2.4: Run; expect PASS**
- [x] **Step 2.5: Commit** — `feat(artifacts): old_str/new_str targeted updates (Claude Gen-2 contract)`

### Task 3: System-prompt artifact section (criteria + per-kind rules + files)

**Files:**
- Modify: `backend/ocd_core/artifact_tools.py::system_prompt_section`
- Test: `backend/tests/test_artifacts.py`

- [x] **Step 3.1: Failing tests** — section mentions: ">20 lines", "one artifact per
  message", "never wrap the content in ``` fences" (no-fence rule), mermaid
  double-quoting of labels, react "default export" + "localStorage" ban + at least
  recharts/lucide-react/d3 in the roster, html single-file + cdn guidance, svg viewBox,
  "old_str" update guidance, and keeps the existing csv + code_execution file-writing
  guidance (xlsx/docx/pptx/pdf named).
- [x] **Step 3.2: Run; expect FAIL**
- [x] **Step 3.3: Implement** the rewritten section (Claude Gen-2 criteria adapted; roster
  must list ONLY libraries the react srcdoc import map actually provides — keep in sync
  with Task 4's `REACT_IMPORTS`).
- [x] **Step 3.4: Run; expect PASS**; also `python -m pytest backend/tests -q` (no regressions — `test_prompts.py`, `test_artifact_streaming.py` especially)
- [x] **Step 3.5: Commit** — `feat(artifacts): Claude-parity system-prompt criteria and per-kind rules`

### Task 4: Frontend srcdoc module (`artifactSrcdoc.ts`) — mermaid + react runtimes

**Files:**
- Create: `desktop/src/state/artifactSrcdoc.ts`
- Create: `desktop/src/state/artifactSrcdoc.test.ts`
- Modify: `desktop/src/components/ArtifactPanel.tsx` (delete local `buildSrcDoc`/`escapeHtml`, import from the new module)

- [x] **Step 4.1: Failing tests** (`artifactSrcdoc.test.ts`), covering:
  - `stripFence`: closed fence unwraps; *unclosed opening fence* (streaming) drops first line; unfenced unchanged; inner fences survive
  - `normalizeMermaid`: strips U+200E/200F/202A–202E/2060–2069/200B/FEFF; leaves Arabic letters intact
  - `jsonForScriptTag`: embeds `</script>` safely (`<` escaping)
  - `rewriteExports`: `export default function App(){}` / `export default class X{}` / `export default () => …` / `export default Identifier` / `export const A = …` → declarations + `__ARTIFACT_DEFAULT__` binding; source without exports unchanged
  - mermaid srcdoc: contains `mermaid@11.16.0`, the JSON-embedded source (decode it back and expect the EXACT user-reported Arabic xychart, fence stripped), `mermaid.render`, an error-card path, and does NOT contain `<pre class="mermaid">`
  - react srcdoc: contains import map pins (react@18.3.1, react/jsx-runtime, lucide-react@0.383.0, recharts, d3, lodash, papaparse, xlsx, mathjs, chart.js, tone, three@0.128.0), `@babel/standalone`, `@tailwindcss/browser`, the rewritten (not raw) source, mount fallback chain `__ARTIFACT_DEFAULT__ ?? App ?? Component`
  - html passthrough + svg wrapping preserved byte-for-byte vs today's behavior
- [x] **Step 4.2: Run; expect FAIL** — `cd desktop && npx vitest run src/state/artifactSrcdoc.test.ts`
- [x] **Step 4.3: Implement the module.** Skeleton:

```ts
export const MERMAID_VERSION = "11.16.0";
export const REACT_IMPORTS: Record<string, string> = { /* pinned jsdelivr +esm map */ };
export function stripFence(s: string): string
export function normalizeMermaid(s: string): string
export function jsonForScriptTag(s: string): string   // JSON.stringify + /</g → <
export function rewriteExports(src: string): string   // binds __ARTIFACT_DEFAULT__
export function buildSrcDoc(doc: Pick<ArtifactDoc,"kind"|"content"|"language">): string
```
  Mermaid srcdoc: CSP meta (unchanged allowlist) + `<script id="src" type="application/json">`
  + pinned mermaid + `mermaid.initialize({startOnLoad:false,securityLevel:'strict'})` +
  `render().then(inject).catch(errorCard(message, source))`. React srcdoc: CSP + import
  map + tailwind browser + JSON-embedded rewritten source + Babel transform
  (`presets [["react",{runtime:"automatic"}],["typescript",{isTSX:true,allExtensions:true}]]`)
  + injected module script + mount epilogue + window.onerror error card.
- [x] **Step 4.4: Run; expect PASS**; wire `ArtifactPanel.tsx` to import { buildSrcDoc } and delete the locals; `npx vitest run` (whole desktop suite) green; `npx tsc -b --noEmit` green.
- [x] **Step 4.5: Commit** — `fix(artifacts): tested srcdoc module — mermaid render pipeline + real react runtime`

### Task 5: Packaged-app CSP + guards

**Files:**
- Modify: `desktop/src-tauri/tauri.conf.json` (app.security.csp)
- Modify: `desktop/src/api/csp.test.ts`

- [x] **Step 5.1: Failing tests** — csp.test.ts: `script-src` exists, contains `'self'`,
  `'unsafe-inline'`, `https://cdn.jsdelivr.net`; `font-src` allows `data:`; existing
  connect-src assertions unchanged.
- [x] **Step 5.2: Run; expect FAIL**
- [x] **Step 5.3: Implement** — extend the csp string:
  `default-src 'self'; script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; connect-src 'self' http://127.0.0.1:8000 ws://127.0.0.1:8000 http://localhost:8000 ws://localhost:8000 https://cdn.jsdelivr.net; img-src 'self' data: https:; style-src 'self' 'unsafe-inline'; font-src 'self' data: https:`
  (connect-src gains jsdelivr because ESM `import()` fetches inside inherited-policy srcdoc frames are governed by script-src, but Babel sourcemap/fetch fallbacks and `three` texture loads use connect/img — keep img-src https: as is.)
- [x] **Step 5.4: Run; expect PASS**
- [x] **Step 5.5: Commit** — `fix(desktop): packaged-app CSP admits sandboxed preview runtimes (documented trade-off)`

### Task 6: Full verification

- [x] `python -m pytest backend/tests -q` → all green
- [x] `cd desktop && npx vitest run` → all green
- [x] `cd desktop && npx tsc -b --noEmit` → clean
- [x] `cd desktop && npm run build` → succeeds
- [x] Live render: write `buildSrcDoc({kind:"mermaid", content:<exact user chart>})` output to a scratch html file, serve locally, open in browser — assert an `<svg>` with 10 bars renders and no "Syntax error in text" appears; screenshot for the report. Same for a react smoke artifact (recharts + tailwind).
- [x] Commit any test-only fixes; update this plan's checkboxes + Deviations.

### File Structure (locked)

- `backend/ocd_core/artifact_tools.py` — tools, prompt, store, sanitization (single home for the artifact contract)
- `backend/tests/test_artifacts.py` — the whole backend contract
- `desktop/src/state/artifactSrcdoc.ts` (+ `.test.ts`) — every srcdoc/preview-runtime decision
- `desktop/src/components/ArtifactPanel.tsx` — chrome only, no srcdoc logic
- `desktop/src-tauri/tauri.conf.json` + `desktop/src/api/csp.test.ts` — packaged-app policy + guard

### Deviations from the approved spec

1. **React module graph moved from jsdelivr `+esm` to esm.sh.** jsdelivr's `+esm`
   rewrites a package's internal `import "react"` to a jsdelivr URL resolved against
   the package's own peer range — reintroducing the two-React-instances hook breakage
   nondeterministically. esm.sh with `?external=react,react-dom` keeps those imports
   bare so the import map pins a single React. Babel, Tailwind, and mermaid stay on
   jsdelivr. Both hosts are in the srcdoc CSP and the Tauri CSP (spec §3.5 wording
   updated accordingly by this deviation; `three` also gained an `?external` -free pin
   since it has no react peer).
2. **`<meta charset="utf-8">` added to every generated srcdoc** (not in the spec):
   srcdoc *strings* don't decode bytes, but any byte-serialized copy (print path,
   future custom-protocol previews, saved files) turned Arabic labels into mojibake —
   caught during the live-render verification, test-guarded now.
3. **`lodash` maps to the CJS build (default-import interop) with a `lodash-es`
   alias** — models write `import _ from "lodash"`, which lodash-es cannot satisfy.
4. **Backend verification excludes `backend/tests/test_anthropic_native.py`** — the
   shared dev venv (`venv312`, provisioned for the pre-fork line) lacks the
   `anthropic` package that origin/main's provider tests import. Pre-existing
   environment gap, unrelated to this change; every other backend test runs and
   passes.
5. **Verification harness detail:** the live-render fixtures were produced by a
   temporary vitest file (`__scratch_render.test.ts`, deleted after use) writing
   `buildSrcDoc` output for (a) the exact reported fenced Arabic xychart and (b) a
   recharts+lucide+Tailwind react smoke component; both verified in a real browser
   (SVG bars + labels intact; component interactive with state updates).
