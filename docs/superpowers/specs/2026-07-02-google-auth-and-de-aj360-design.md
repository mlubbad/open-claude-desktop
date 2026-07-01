# De-AJ360 cleanup + Google-only auth — design

**Date:** 2026-07-02
**Status:** Approved in brainstorming → spec for review
**Branch:** `feat/google-auth-de-aj360`, stacked on `feat/optional-bigquery-tool-persistence`
(which provides the `ocd_app` rename + the optional-BigQuery toggle this work edits).

## Goals

1. **De-AJ360 the generic shell** — remove the bundled demo MCP server and AJ360 branding
   from plugins / connectors / MCP / tool *surface*, WITHOUT touching the live BigQuery
   capability or its `aj360.*` datasets.
2. **Replace username/password auth with Google-only OAuth** — "Sign in with Google";
   any Google account may register/log in (open register).

These are two independent sub-projects (A and B) sharing one branch; they can commit/ship
separately.

## Non-goals / boundaries (explicit)

- **KEEP** the BigQuery capability, `search_schema`/`run_sql`, the `aj360.*` dataset
  queries, `GCP_PROJECT_ID`, and the AJ360-specific SQL hard rules. The (now optional)
  BigQuery prompt still *describes the AJ360 data domain* because that is literally the
  data it queries — de-branding it there would misdescribe live data. We de-brand the
  **UI/surface**, not the data-domain description. **(Confirmed with user.)**
- No users/DB table. Open register = a successful Google login mints the existing HMAC
  session token; the token *is* the session.
- No domain restriction / allowlist (any verified Google email).
- OAuth `state` is held in-process (single-worker only; noted, not solved here).
- No change to `ocd_core` backend naming or the `aj360.*` dataset identifiers.

---

## Sub-project A — De-AJ360 cleanup (BigQuery kept)

**A1. Remove the demo MCP server**
- Delete `mcp_servers/demo_server.py`.
- Remove the `aj360_demo` object from `mcp_servers.json`.
- Remove `integrations.add_demo_mcp_server()` (`backend/ocd_core/integrations.py` ~L309-312).
- Remove the demo registration route in `backend/app/routes/integrations.py`
  (`POST /mcp-servers/demo`) and `api_client.add_demo_mcp_server` (frontend).
- Remove `AppState.add_demo_mcp` and the "Add demo MCP server" `rx.menu.item` in
  `frontend/ocd_app/components/composer.py`.

**A2. Drop the `aj360_plugin_` tool-name prefix → `plugin_`**
- `backend/ocd_core/integrations.py:53` builds plugin module/tool names as
  `aj360_plugin_<stem>`. Rename the prefix to `plugin_`. This is a **coordinated** change:
  update BOTH the name emitted by `plugin_tools()` AND the dispatch path
  (`run_plugin` / `run_tool`) that strips the prefix to find the plugin module, so plugin
  calls still resolve. Verify with a test that a known plugin (e.g. `calculator`) still
  runs under the new name.

**A3. De-brand labels/docstrings (surface only)**
- `frontend/ocd_app/components/composer.py`: BigQuery toggle label `"BigQuery (AJ360)"` →
  `"BigQuery"`.
- `frontend/ocd_app/ocd_app.py` module docstring `"AJ360 — Projects UI…"` →
  `"Open Claude Desktop — Projects UI…"`.
- Grep the frontend + backend for user-visible/comment "AJ360" mentions that are pure
  branding (NOT dataset/domain references) and neutralize them. Explicitly leave:
  `aj360.*` table refs, `GCP_PROJECT_ID`, and the BigQuery prompt's data-domain text.

**A tests:** plugin dispatch still resolves under `plugin_` (call `calculator` via
`run_tool`); the demo route is gone (404); `mcp_servers.json` has no `aj360_demo`.

---

## Sub-project B — Google-only auth (any Google account)

The existing HMAC session token (`make_token`/`decode_token`/`verify_token`, signed by
`APP_AUTH_SECRET`/`CHAINLIT_AUTH_SECRET`) is reused unchanged. Only the *identity proof*
changes: Google OAuth instead of username/password.

**B1. Config (`.env`, read at call time)**
- `GOOGLE_OAUTH_CLIENT_ID`, `GOOGLE_OAUTH_CLIENT_SECRET`
- `OCD_OAUTH_REDIRECT_URI` (default `http://localhost:8000/auth/google/callback`)
- `OCD_FRONTEND_URL` (default `http://localhost:3000`)
- Session signing secret: reuse existing resolution (`APP_AUTH_SECRET` → `CHAINLIT_AUTH_SECRET` → `AJ360_AUTH_SECRET`).

**B2. `backend/ocd_core/auth.py`**
- Redefine `auth_enabled()` → `bool(GOOGLE_OAUTH_CLIENT_ID and GOOGLE_OAUTH_CLIENT_SECRET and _secret())`.
- Remove `credentials_ok`, `_expected_user`, `_expected_pass` (and `APP_USERNAME`/`APP_PASSWORD` usage).
- Keep `make_token` / `decode_token` / `verify_token` / `_secret` / `_TTL` verbatim.
- (Unconfigured → `auth_enabled()` False → open, preserving local-dev-without-OAuth, same
  as today.)

**B3. `backend/ocd_core/google_oauth.py` (new)** — thin wrapper over `google-auth-oauthlib`:
- `build_auth_url(state) -> str` (scopes `openid email profile`, `redirect_uri`, `access_type=offline`, `prompt=select_account`).
- `exchange_code(code) -> str` — exchange the auth code, verify the returned id_token via
  `google.oauth2.id_token.verify_oauth2_token`, return the **verified** email (raise on
  unverified/invalid). In-process `state` store (module-level dict/set) created on
  `build_auth_url`, consumed/validated on callback.

**B4. `backend/app/routes/auth.py`** — replace `POST /auth/login` with:
- `GET /auth/google/login` → create `state`, `RedirectResponse` to `build_auth_url(state)`.
- `GET /auth/google/callback?code&state` → validate `state`; `email = exchange_code(code)`;
  `token = make_token(email, int(time.time()))`; `RedirectResponse` to
  `{OCD_FRONTEND_URL}/auth/complete?token={token}`. On any failure → redirect to
  `{OCD_FRONTEND_URL}/login?error=…`.
- `current_user` (`app/deps.py`) unchanged (Bearer → `decode_token`).
- Remove `LoginRequest` from `schemas.py` (keep `TokenResponse` only if still referenced;
  otherwise remove).

**B5. Frontend (`frontend/ocd_app/`)**
- `auth.py` `login_page`: replace the username/password form with a single
  **"Sign in with Google"** button — an `rx.link`/redirect to
  `f"{api_client._BASE}/auth/google/login"`. Remove `AuthState.username/password/do_login`
  and the error text tied to bad credentials. Keep `auth_token` cookie, `is_authenticated`,
  `require_login`, `do_logout`.
- New page `/auth/complete` (`aj360_app.py`→`ocd_app.py` route table): `on_load` handler
  `AuthState.complete_login` reads `token` from the query params, sets
  `self.auth_token = token`, calls `api_client.configure(token=token)`, redirects to `/`.
  If no token → redirect `/login`.
- `api_client.py`: remove `login(username, password)`. Add nothing else (token arrives via
  the cookie set in `/auth/complete`; `_headers()` already sends it as Bearer once
  `configure(token=…)` is called — note the existing app reads the cookie into the client
  on load; confirm the token is applied on every page load, e.g. via an on_load that
  `configure`s from the cookie).

**B6. Setup steps (documented in the spec/plan, for the user to perform):**
Google Cloud Console → APIs & Services → OAuth consent screen (**External**, add your
email as a test user or publish) → Credentials → Create Credentials → OAuth client ID →
**Web application** → Authorized redirect URIs: `http://localhost:8000/auth/google/callback`
→ copy Client ID + Secret into `.env` as `GOOGLE_OAUTH_CLIENT_ID` / `GOOGLE_OAUTH_CLIENT_SECRET`.
(Claude cannot create this; user pastes the two values.)

**B tests:**
- `auth_enabled()` true iff Google client + secret + signing secret set; false (open) otherwise.
- Callback logic: with `exchange_code` monkeypatched to return `alice@example.com`, the
  callback mints a token that `decode_token` resolves to `alice@example.com`, and redirects
  to `{OCD_FRONTEND_URL}/auth/complete?token=…`.
- `current_user` accepts a `make_token(email)` Bearer; rejects garbage when `auth_enabled()`.
- `state` mismatch on callback → rejected.
- Frontend: `login_page` renders the Google button linking to `…/auth/google/login`;
  `complete_login` stores the token + redirects.
- Manual (after user supplies real credentials): full OAuth round-trip; unauthorized →
  `/login`; the demo MCP server is gone; `calculator` plugin still runs.

## Data flow (auth)

`/` → `require_login` → `/login` → **Sign in with Google** → backend `/auth/google/login`
→ Google consent → backend `/auth/google/callback` (verify email, mint HMAC token) →
frontend `/auth/complete?token=…` (store cookie, configure client) → `/` authenticated.
API calls carry the Bearer token; `current_user` validates it.

## Compatibility

- Existing conversations/data untouched.
- Local dev without Google config → auth open (unchanged behavior).
- `.env.example` gains the four new `GOOGLE_OAUTH_*` / `OCD_*` keys; the old
  `APP_USERNAME`/`APP_PASSWORD` become unused (leave in `.env.example` as deprecated or
  remove — plan will pick one).
