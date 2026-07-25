# Marketplace plugin remediation — 2026-07-25

Executes `2026-07-25-marketplace-plugin-review-handoff.md` (findings F-01–F-04).
Work done on `codex/marketplace-plugin-remediation`, integrated into local
`main` (not pushed).

## Changes

| Commit | What |
|---|---|
| `d62e26f` | F-01: revert `b2987e5` — removed the four preinstalled catalog duplicates from `plugins/`; `content/marketplace/` is the single canonical source |
| `d1f38f0` | F-01 guard: fresh-runtime tests — the real bundled catalog starts `installed=False` and its names are absent from `list_plugins()` |
| `82eebcf` | Canonical catalog files must load via `integrations._load_plugin_module` and expose NAME / TOOL / run |
| `140898a` | F-02: base64_tool rejects unknown/empty/non-string `direction` instead of silently encoding |
| `12ee402` | F-03: word_count uses `splitlines()` + `str.isspace()` (CRLF, bare CR, NBSP, Unicode whitespace) |
| `0aa3264` | F-04: color_convert accepts a balanced, case-insensitive `rgb(...)` wrapper — it can round-trip its own output |
| `81d56f0` | roman_numeral round-trip (1–3999) + rejection pins (verified non-finding) |

New tests: `backend/tests/test_marketplace_plugins.py` (install-state contract +
runtime-loader contract, 3 tests) and
`backend/tests/test_marketplace_plugin_behavior.py` (35 behavior tests;
deliberately free of `ocd_core` imports so it runs in seconds).

## Deliberate decisions

- base64: an absent `direction` still defaults to encode (the tool schema marks
  it required, so the default only affects schema-less callers); explicitly
  provided invalid values now return an error.
- base64 strict decoding retained: line-wrapped / MIME base64 is rejected, and a
  test pins that. Accepting wrapped input remains an open product decision
  (handoff F-02, lower-priority note).
- word_count line policy: `splitlines()` universal line boundaries; a trailing
  terminator adds no extra line; empty text has 0 lines.
- color_convert: only a *balanced* `rgb(...)` wrapper is accepted; unbalanced
  forms remain rejected.

## RESOLVED (2026-07-26) — packaged marketplace delivery

Packaged desktop builds previously had no delivery path for the bundled catalog:
the sidecar's per-user data root starts without `content/marketplace/`, and
neither `backend/ocd-backend.spec` nor `desktop/src-tauri/tauri.conf.json`
bundled these assets — in a packaged install the marketplace was empty. The
handoff's "release-completeness correction" required: (1) ship the catalog as
immutable bundled assets exposed without copying them into live installed
state; (2) keep user-installed plugins in the writable per-user `PLUGINS_DIR`;
(3) an installed-package smoke test.

Resolution — **PyInstaller datas**, not Tauri resources: the backend is the
catalog's only consumer, so the asset ships inside the frozen sidecar itself
(`backend/ocd-backend.spec` bundles `content/marketplace` → extracted under
`sys._MEIPASS`; stray `__pycache__` is stripped from datas so a dev-machine
build never ships stale bytecode). A Tauri resource would have needed the shell
to compute `resource_dir()` and pass a new env var — any launcher missing it
(including a standalone run of the frozen sidecar, which `sidecar.py` supports)
would silently regress to an empty marketplace, and CI can't exercise that path
without a Rust build. `config._default_marketplace_dir()` resolves
`MARKETPLACE_DIR` into the bundle when `sys.frozen` is set (the `MARKETPLACE_DIR`
env override still wins; source/dev checkouts keep the repo-root default). The
bundle is immutable and outside the data root, so the catalog can never be
conflated with installed state; installs still only COPY into `PLUGINS_DIR`.

Tests (`backend/tests/test_marketplace_packaging.py`, 5): the spec keeps
shipping the catalog at the exact in-bundle path config resolves; frozen
resolution lands in the bundle, never the data root; dev resolution and the env
override are pinned; and an installed-package smoke test runs the full
lifecycle from an empty app-data dir (catalog visible, entries `installed=False`
→ install one → run it → uninstall → catalog intact, bundle byte-identical).

## Validation

- Python 3.12.10 (CI interpreter): 51 passed across `test_marketplace.py`,
  `test_plugins_cache.py`, `test_marketplace_plugins.py`,
  `test_marketplace_plugin_behavior.py`; `ruff check backend
  content/marketplace plugins` clean.
- Python 3.14.6: same 51 passed (known opik / pydantic-v1 warning on 3.14);
  ruff clean.
- Work was done in an isolated worktree and integrated with `--ff-only`; the
  protected dirty files in the main checkout were never staged or modified.
