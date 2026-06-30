# In-app BigQuery reconnect — design

**Date:** 2026-06-30
**Status:** Approved (brainstorming) → ready to implement
**Author:** Mohammed Lubbad (with Claude)

## Problem

BigQuery uses Application Default Credentials (`google.auth.default()` in
`ocd_core/bigquery.py`). User ADC tokens expire; when they do, the agent turn
surfaces `Reauthentication is needed. Please run gcloud auth application-default
login` and the user must drop to a terminal. We want this handled **in-app**.

Decision (brainstorming): stay on **user ADC** (not a service account), so
expiry recurs — an in-app "Reconnect Google" affordance is worth building.
Reuse the existing gcloud ADC mechanism (no full OAuth web flow, no token
storage, no multi-user). Local/loopback only.

## Approach

A button/banner that triggers `gcloud auth application-default login` on the
host (opens the user's browser via the loopback flow), then refreshes the
cached BigQuery client. The frontend polls a status endpoint until reconnected.

## Components

### Backend — `ocd_core/bigquery.py`
- `needs_reauth(err: str) -> bool` — true for ADC-expiry signatures:
  `Reauthentication is needed`, `Reauthentication failed`, `invalid_grant`,
  `RefreshError`, `invalid_rapt`, `Could not automatically determine credentials`.
- `reset_bq_client()` — clears the cached `_bq_client` so the next call rebuilds
  from fresh ADC.
- `execute_sql` / `_dry_run`: when the error matches `needs_reauth`, add
  `auth_expired: true` to the returned dict (so the UI shows reconnect, not a
  generic failure).

### Backend — `app/routes/bigquery.py` (new), registered in `app/main.py`
- `GET /bigquery/status` → `{connected: bool, project: str, account: str|None}`.
  `connected` via a cheap `SELECT 1` dry-run (0 bytes); on `needs_reauth` error
  → `connected=false`. `account` from the ADC userinfo if cheaply available,
  else null.
- `POST /bigquery/reconnect` → `subprocess.Popen(["gcloud","auth","application-
  default","login"])` (no wait — loopback flow, no stdin), then
  `reset_bq_client()`, returns `{started: true}`. If gcloud is missing →
  `{started: false, error: "..."}` with the manual command.

### Frontend — Reflex (`aj360_app/state.py` + a small component)
- State: `bq_auth_expired: bool`, `bq_reconnecting: bool`, `bq_connected: bool`.
- The agent turn already streams a backend `error` event; when its text matches
  reauth (or a turn/SQL result carries `auth_expired`), set `bq_auth_expired`.
- Inline chat banner: **⚠️ BigQuery needs to reconnect → [Reconnect Google]**.
- Click → `api_client` POST `/bigquery/reconnect` → show "Opening Google sign-in
  in your browser… complete it, then retry." → poll `/bigquery/status` (a few
  seconds apart) → on `connected`, clear the banner: "Reconnected ✓ — retry."

## Error handling
- gcloud not on PATH → banner shows the manual fallback command.
- Sign-in not completed (status stays disconnected after N polls) → "Sign-in
  didn't complete — try again."
- Reconnect spawned but still invalid → keep banner + show error.

## Security / scope
- `/bigquery/reconnect` spawns a local process; backend binds loopback
  (`127.0.0.1`) by default — keep it that way. Single-user desktop scope.
- YAGNI: no OAuth client registration, no refresh-token storage, no remote/
  multi-user — those are only worth it if hosting changes.

## Testing
- Unit: `needs_reauth()` over a table of error strings (expiry vs unrelated).
- Unit: `reset_bq_client()` clears the cache (next `get_bq_client` rebuilds).
- Route: `/bigquery/status` with a mocked client (connected + expired cases);
  `/bigquery/reconnect` asserts `Popen` invoked + client reset (mock subprocess).
- Manual: after an expiry, banner → Reconnect → `SELECT 1` succeeds.
