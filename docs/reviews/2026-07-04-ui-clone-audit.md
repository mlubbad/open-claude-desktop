# UI-clone audit — desktop client vs Claude Desktop design structure

> 2026-07-04. Six-dimension multi-agent audit (shell/sidebar, chat, settings/panels,
> cowork/code, tokens, UX/a11y). Target: exact layout/structure/UX parity with
> Claude Desktop, ORIGINAL brand values (our clay accent, warm canvas, open serif —
> no third-party brand colours, logo, or licensed fonts). Note: the shell & chat
> scores predate commit 88994d0, which implemented the sidebar-tabs shell, hero
> empty state, and two-row composer.

# Claude Desktop Clone — Desktop UI Audit Synthesis

**Composite: ~43/100.** The functional layer (hooks, reducers, callbacks) and color-token architecture are strong; the gap is almost entirely structural composition and metric conformance. Nothing found requires deleting a feature — every fix is a re-home or restyle.

## 1. Scorecard

| Area | Score | Verdict |
|---|---|---|
| Settings + management panels | 25/100 | All functions exist but scattered across three 560px modals; no unified two-pane Settings, no Skills page, no tables. |
| Cowork + Code surfaces | 30/100 | Complete layout-agnostic hooks trapped in utility split-panes; no composer-forward homes anywhere. |
| App shell + Sidebar | 35/100 | Right bones (sunken rail, hairlines, 3 modes) but mode switcher in topbar and the entire Claude nav stack (Projects/Artifacts/Customize, Recents, footer) missing. |
| Chat surface | 54/100 | Transcript is close (760px column, thinking block, tool cards); empty state and composer miss the signature hero-card pattern. |
| Token/system conformance | 55/100 | Excellent color tokens light/dark; metric layer (40px controls, radius scale, display type ramp, tracking) largely absent. |
| UX / a11y / dark parity | 58/100 | Good keyboard and focus foundations; dark mode breaks in load-bearing spots, div rows and hover-only actions block keyboard users. |

## 2. What already matches

- Complete tokenized light/dark palette with `data-theme` override + `prefers-color-scheme` fallback; zero off-brand hex in components; hairline-first elevation with the sanctioned faint shadow.
- Shell geometry: 260px sunken sidebar + flexible main column; 760px centered reading column shared by messages/composer/errors.
- Transcript quality: markdown prose with serif headings, collapsible "Thought for Ns" block, structured tool cards, hover message actions, code-copy, jump-to-latest.
- All three modes (Chat/Code/Cowork) exist; recency bucketing implemented and tested (`state/grouping.ts`).
- Entire functional inventory is layout-agnostic and reusable: `useCowork`/`useSchedules`/`useCode`, transcript replay via the live-chat reducer, 20+ settings/connector/plugin callbacks, `useSkills`, draft persistence, slash menu, Cmd+K palette with content search.
- Keyboard flows (Enter/Shift+Enter, palette, `?` help), global `:focus-visible` shape, tablist semantics on the switcher, pill radius on chips/badges.

## 3. Prioritized worklist

### P0 — defines the Claude Desktop feel

1. **Rebuild the sidebar nav stack.** Mode switcher (Chat/Cowork/Code) as first sidebar child with category-tab active (surface bg + ink, never accent fill); pencil-icon "New chat" row; Projects / Artifacts / Customize nav rows; single uppercase "Recents" caption + flat ~10–15 list + "View all" row; pinned footer (avatar, name, plan line, chevron) with update-banner slot above it. *Files:* `Sidebar.tsx`, `App.tsx`, `styles.css`. *Re-homed functions:* project `<select>` create/manage → Projects row affordances; `groupByRecency` → the View-all history page (keep, don't delete).
2. **Slim the topbar; relocate its controls.** Drop brand text; keep chat title + project chip. Model pill → composer bottom-right; Connectors/Plugins buttons → deep links into the unified Settings modal; theme/export → overflow menu. *Files:* `App.tsx`, `Composer.tsx`, `styles.css`. *Re-homed:* model switching, connectors/plugins entry points — all callbacks unchanged.
3. **Hero composer empty state (chat).** When `messages.length === 0`: serif-400 greeting (~40–44px, negative tracking, brand mark above), big composer card (16–20px radius, generous padding), one-line muted notice under it, suggestion chips below that **prefill** instead of send; hide the bottom footer until messages exist. *Files:* `App.tsx`, `Composer.tsx`, `styles.css`, `state/starters.ts`. *Re-homed:* "Bring your own model" subline → notice under composer.
4. **Two-row composer.** Textarea on top; controls row with circular "+" attach (bottom-left) and model pill + effort selector + mic + circular 36px accent send (bottom-right); `:focus-within` accent border + 3px ring; card floats on canvas (transparent footer, no border-top). *Files:* `Composer.tsx`, `App.tsx`, `styles.css`.
5. **User message → light card.** `--surface-2`/hairline + ink text, 12px radius, keep right alignment; accent reserved for send/primary. *Files:* `styles.css`, `Message.tsx`.
6. **Unified Settings modal.** New `SettingsModal.tsx`: `min(960px, 94vw)`, 230px left-nav (search input on top) + scrolling right pane; groups Settings / Desktop app / Customize (Skills, Connectors, Plugins). Map existing pages: profile → Account/General; web-search → Capabilities; BYOK providers → Models; ConnectorsPanel body → Customize>Connectors; PluginsPanel body → Customize>Plugins. `openSettings(page)` deep links from topbar + palette. **All 20+ callbacks pass through unchanged — zero function loss.** *Files:* new `SettingsModal.tsx`, `Settings.tsx`, `ConnectorsPanel.tsx`, `PluginsPanel.tsx`, `App.tsx`, `styles.css`. *Re-homed:* **ProjectPanel does NOT fold in** — it moves to a project detail view in the main surface (instructions + knowledge cards), preserving autosave, capacity meter, upload, delete.
7. **Cowork home.** Centered ~720px column: serif hero + safety subline, big composer card (reuses chat composer pattern; submit = existing `onStart`), selector row (project/folder picker bound to `CoworkConfig.projectId` + "Act" picker replacing hardcoded `effort:"High"`), "Active" section (status dots from `statusBadge`, meta from `updated_at`/`events`, Review button → `onOpen`), "Scheduled" section (clock icon + next-run computed client-side + toggle/delete), dotted-grid background. *Files:* `CoworkPanel.tsx`, `App.tsx`, `styles.css`, `api/client.ts` (optional `next_run`). *Re-homed:* delegate textarea → home composer; schedule create form → "+ New schedule" popover (`sched.add` unchanged); detail pane → Review view with back affordance.
8. **Code home.** Empty code view gets serif greeting + big composer + code-flavored chips; mount tree/viewer only once the session has messages (or behind a Workspace toggle). Keep `useCode` refresh/reopen wiring as-is. *Files:* `App.tsx`, `CodePanel.tsx`, `styles.css`.
9. **Dark-mode load-bearing fixes.** Per-theme `--ring` token (accent at 15%/28% alpha) for all focus rules; `color-scheme: light` / `dark` synced to `data-theme` in both blocks; `.composer-send` `color: var(--accent-fg)` not `#fff`. *Files:* `styles.css`.

### P1 — strong contributors

1. **Metric primitives + sweep** (single pass): `--radius-sm/md/lg/pill` tokens and sweep 6px→8, 10px→12, badges→pill, composer→16; `.btn` primitive (40px / 12×20 / 14px-500) migrating `.conn-submit`, approval, upload, authorize buttons; 40px input primitive with one surface token; `.caption` class (12px/500/uppercase/+1.5px) applied to all section labels incl. sidebar Recents; `body { line-height:1.55 }`; `--shadow-soft` + `--overlay` tokens replacing heavy palette/slash-menu/jump-latest shadows (dark-tuned values). *Files:* `styles.css`.
2. **Kill accent-fill actives everywhere.** Tabs/chips → surface bg + ink + strong border; keyboard-highlighted rows (palette, slash menu, code tree) → `--surface-2` + ink. *Files:* `styles.css` (`.conn-tabs`, `.model-row .model`, `.plan-toggle`, `.slash-menu li`, `.palette-list li`, `.code-file`, `.artifact-tabs`).
3. **Icon system.** Shared 36px circular icon-button primitive; small `Icon` component with 16px stroke SVGs replacing every emoji/glyph (trash, clock, pencil, pin, sun/moon, download, plus, ✕); `aria-label` on all icon-only buttons and enable-checkboxes. *Files:* new `Icon.tsx`, `styles.css`, `App.tsx`, `Sidebar.tsx`, `Composer.tsx`, `Message.tsx`, all panels, `state/starters.ts`, `state/theme.ts`.
4. **Keyboard access + dialogs.** Escape closes topmost modal (priority chain); `role="dialog"` + `aria-modal` + labelled title + initial focus + minimal trap on all overlays; button-ize div rows (recents, cowork tasks, file tree w/ tree semantics); focus-reveal rules for all hover-only actions; pin actions visible on the last assistant message (`isLast` class). *Files:* `App.tsx`, `useKeyboard.ts`, `Sidebar.tsx`, `CoworkPanel.tsx`, `CodePanel.tsx`, `Message.tsx`, all modals, `styles.css`.
5. **Settings content patterns.** Skills page (name/updated/author table + Browse/Add — extend `SkillSummary` + backend payload); Connectors page filter chips + "POPULAR FOR <role>" tiles + Connector/Type/Status table, add-form behind "Add connectors" (all flows incl. `.mcpb` install and Demo survive behind explicit buttons); Plugins table (Plugin/Author/Skills/Last updated) + search/Browse/Add, marketplace rules preserved. *Files:* `SettingsModal.tsx` pages, `api/client.ts`, backend `/skills` `/plugins` `/marketplace`.
6. **View-aware sidebar.** Pass `view` into Sidebar; cowork gets New task / Scheduled / Dispatch (Beta) rows + Scheduled/Dispatch/Recents groups from existing hooks. *Files:* `Sidebar.tsx`, `App.tsx`.
7. **Remaining chrome polish with visible payoff:** thinking-toggle as pill chip; themed thin scrollbars; `prefers-reduced-motion` media rule + auto jump-scroll; serif display ramp (h1–h4 weight 400 with per-level negative px tracking, `.display-xl` for heroes, drop the 600 on `.empty h1`). *Files:* `styles.css`, `Message.tsx`, `useAutoScroll.ts`.

### P2 — polish

- 4px-grid spacing sweep (7→8, 5→4, 3→4); snap fractional sizes (12.5/13.5/11.5) and weight 550→500. *`styles.css`*
- Mono/code type to 14px/1.6 (or one `--code-size` token) across viewer, tool-input, artifact-code, approval-input. *`styles.css`*
- `.conv-item` transparent 1px border (no selection shift); pin marker as leading icon span, not "★ " in the title string. *`styles.css`, `Sidebar.tsx`*
- Card/modal padding to 24–32px (settings pane, shortcuts, approval, artifact-card). *`styles.css`*
- Slash-menu Escape dismisses menu only (stop erasing the draft). *`Composer.tsx`*
- Listbox ARIA (role=listbox/option + `aria-activedescendant`) on palette + slash menu; `aria-expanded` on thinking chip + Scheduled header. *`CommandPalette.tsx`, `Composer.tsx`, `Message.tsx`, `CoworkPanel.tsx`*
- Platform-aware shortcut glyphs (⌘ vs Ctrl+). *`state/shortcuts.ts`*
- Replace `window.prompt` with inline rename + small themed project dialog. *`Sidebar.tsx`, `App.tsx`*
- `--artifact-canvas` token + `color-scheme` meta injected into artifact srcDoc. *`styles.css`, `ArtifactPanel.tsx`*
- Turn rhythm: `.msg` vertical padding 6→12px. *`styles.css`*

## 4. Suggested PR slicing

1. **PR 1 — Token & primitive foundation (P0-9 + P1-1/2 + P2 sweeps).** `--ring`, `color-scheme` sync, radius scale, `.btn`/input/icon-btn/`.caption` primitives, shadow/overlay tokens, accent-active sweep, body line-height, scrollbars, reduced-motion, display type ramp. Almost entirely `styles.css`; low risk, everything after it inherits the system.
2. **PR 2 — Shell rebuild (P0-1/2 + P1-6).** Sidebar nav stack + footer + Recents/View-all, slim topbar, view-aware sidebar, deep-link stubs for Settings pages. Re-homes project select and model pill (pill lands temporarily where PR 3 will mount it).
3. **PR 3 — Composer-forward surfaces (P0-3/4/5/7/8 + P1-7).** Two-row composer with model/effort/mic, chat hero empty state, user-bubble card, Cowork home + Review view, Code home. One PR because all three homes share the composer-card component.
4. **PR 4 — Unified Settings + tables + a11y (P0-6 + P1-3/4/5 + remaining P2).** `SettingsModal` shell with grouped nav and deep links, Skills/Connectors/Plugins pages, ProjectPanel relocation to main-surface project view, icon component rollout, Escape/dialog/keyboard-row/focus-reveal fixes, API field extensions (`author`, `updated_at`, skills count, `next_run`).