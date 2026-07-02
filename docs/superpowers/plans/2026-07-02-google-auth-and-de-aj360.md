# De-AJ360 cleanup + Google-only auth — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove the "AJ360 Demo" MCP server and AJ360 branding from the product surface (keeping the BigQuery capability + `aj360.*` datasets), and replace username/password login with Google-only OAuth ("Sign in with Google", any Google account).

**Architecture:** Two independent sub-projects on branch `feat/google-auth-de-aj360` (stacked on `feat/optional-bigquery-tool-persistence`). **A** deletes the user-facing demo registration + de-brands labels. **B** reuses the existing HMAC session token (`ocd_core.auth`) unchanged and only swaps the identity proof: a Google OAuth Authorization-Code round-trip mints the token. No users table; a verified Google email → a signed token that *is* the session.

**Tech Stack:** FastAPI, SQLModel, Reflex 0.9.5, `google-auth` + `google-auth-oauthlib`, pytest + respx, HMAC session tokens.

---

## Deviations from the approved spec (read first)

The spec said "delete `mcp_servers/demo_server.py`". **We keep that file** — it is a live test fixture that `backend/tests/test_mcp_registry.py` spawns for real (repo-root path `mcp_servers/demo_server.py`). It contains **no AJ360 branding** (a neutral echo/word_count server). Deleting it would break the MCP-registry integration tests for zero branding benefit. We remove only the **user-facing registration** (the `aj360_demo` entry named "AJ360 Demo", `add_demo_mcp_server()`, the `POST /mcp-servers/demo` route, and the frontend one-click). This fully satisfies "remove AJ360 Demo from MCP servers" while keeping the suite green.

Other spec-vs-reality adjustments already folded into tasks below:
- `backend/tests/test_new_endpoints.py::test_add_demo_mcp_server` asserts the demo route → **replaced** with a 404 assertion (Task A1).
- `frontend/tests/test_api_client.py::test_login_returns_token_and_sets_bearer` calls `api_client.login()` → **replaced** with a `configure()`-sets-Bearer test (Task B3).
- `backend/tests/test_ocd_auth.py` / `test_app_health_auth.py` use `credentials_ok` + `/auth/login` → **updated** for Google (Task B4).
- Root `tests/test_auth.py` loads the deleted `aj360_app/aj360_app/auth.py` path — it is **already broken** by the earlier rename → **deleted** as legacy (Task B4).
- The `aj360_plugin_` string (integrations.py:53) is only the internal `importlib` module id, **not** a tool name; dispatch matches on `NAME`/stem. Renaming it is cosmetic — a test locks that in (Task A2).

**Do NOT commit these pre-dirty / runtime files** (they were already modified before this work): `mcp_servers.json`, `settings.json`, `frontend/reflex.lock/package-lock.json`, `backend/ocd_local.db`. Where a task edits `mcp_servers.json`, that edit is a **working-tree runtime cleanup only — leave it unstaged.**

---

## File Structure

**Sub-project A (created/modified):**
- `mcp_servers.json` — runtime registry; drop the `aj360_demo` object (unstaged).
- `backend/ocd_core/integrations.py` — remove `add_demo_mcp_server`; rename plugin importlib prefix.
- `backend/app/routes/integrations.py` — remove `POST /mcp-servers/demo`.
- `backend/tests/test_new_endpoints.py` — demo-route test → 404 test.
- `backend/tests/test_plugins_dispatch.py` *(new)* — plugin still resolves under new prefix.
- `frontend/ocd_app/api_client.py` — remove `add_demo_mcp_server`.
- `frontend/ocd_app/state.py` — remove `add_demo_mcp`; de-brand comment.
- `frontend/ocd_app/components/composer.py` — remove demo menu item; label `BigQuery (AJ360)`→`BigQuery`.
- `frontend/ocd_app/ocd_app.py` — de-brand module docstring.

**Sub-project B (created/modified):**
- `backend/pyproject.toml` — add `google-auth-oauthlib`.
- `backend/ocd_core/google_oauth.py` *(new)* — auth-URL builder, code exchange, in-process CSRF `state` store.
- `backend/tests/test_google_oauth.py` *(new)*.
- `backend/app/routes/auth.py` — replace `/auth/login` with `/auth/google/login` + `/auth/google/callback`.
- `backend/app/schemas.py` — remove `LoginRequest` + `TokenResponse`.
- `backend/tests/test_auth_google_routes.py` *(new)*.
- `backend/ocd_core/auth.py` — Google-keyed `auth_enabled()`; remove `credentials_ok`/`_expected_user`/`_expected_pass`.
- `backend/tests/test_ocd_auth.py`, `backend/tests/test_app_health_auth.py` — updated.
- `tests/test_auth.py` — deleted (legacy, already broken).
- `frontend/ocd_app/auth.py` — "Sign in with Google" + `complete_login`; drop username/password.
- `frontend/ocd_app/ocd_app.py` — register `/auth/complete`.
- `frontend/tests/test_api_client.py` — login test → configure test.
- `.env.example`, `SECURITY.md` — Google OAuth keys + wording.

---

## Conventions for every task

- **Run backend tests from the repo root** (test files import both `ocd_core.*` and `backend.app.main`):
  `./venv312/Scripts/python.exe -m pytest <path> -v`
- **Run frontend tests from `frontend/`**:
  `cd frontend && "../venv312/Scripts/python.exe" -m pytest tests/<file> -v`
- **Syntax-check a frontend module** (no Reflex runtime needed):
  `./venv312/Scripts/python.exe -m py_compile frontend/ocd_app/<file>.py`
- Follow **superpowers:test-driven-development**: write the failing test, see it fail, implement, see it pass, commit.
- Commit messages end with the repo's `Co-Authored-By` trailer.

---

# Sub-project A — De-AJ360 cleanup (BigQuery kept)

### Task A1: Remove the user-facing "AJ360 Demo" MCP registration

**Files:**
- Modify: `backend/tests/test_new_endpoints.py:67-72`
- Modify: `backend/app/routes/integrations.py:78-81`
- Modify: `backend/ocd_core/integrations.py:308-312`
- Modify (unstaged runtime): `mcp_servers.json:2-74`
- Keep untouched: `mcp_servers/demo_server.py`, `backend/tests/test_mcp_registry.py`

- [ ] **Step 1: Rewrite the demo-route test to expect it gone.** In `backend/tests/test_new_endpoints.py`, replace the whole `test_add_demo_mcp_server` function (lines 67-72) with:

```python
def test_demo_mcp_route_removed():
    # The "AJ360 Demo" one-click registration route has been removed.
    assert client.post("/mcp-servers/demo").status_code == 404
```

- [ ] **Step 2: Run it — expect FAIL (route still present).**

Run: `./venv312/Scripts/python.exe -m pytest backend/tests/test_new_endpoints.py::test_demo_mcp_route_removed -v`
Expected: FAIL (route currently exists, so the status is not 404).

- [ ] **Step 3: Remove the route + handler.** In `backend/app/routes/integrations.py`, delete these lines (78-81, including the leading blank line):

```python

@router.post("/mcp-servers/demo")
def add_demo_mcp(user: str = Depends(current_user)) -> dict:
    return integrations.add_demo_mcp_server()
```

- [ ] **Step 4: Remove the factory.** In `backend/ocd_core/integrations.py`, delete `add_demo_mcp_server` (lines 308-312):

```python
def add_demo_mcp_server() -> dict:
    """Register the bundled demo MCP server (mcp_servers/demo_server.py) using the
    current Python interpreter — no node, no network, no secrets."""
    return add_mcp_server("AJ360 Demo", "${PYTHON}",
                          ["${REPO_ROOT}/mcp_servers/demo_server.py"])
```

- [ ] **Step 5: Runtime cleanup (DO NOT stage/commit this file).** In `mcp_servers.json`, delete the first array element — the object whose `"id": "aj360_demo"` / `"name": "AJ360 Demo"` (lines 2-74) — leaving `playwright` as the first entry. This is app-managed runtime state and is already dirty; keep it out of the commit.

- [ ] **Step 6: Run the affected tests — expect PASS.**

Run: `./venv312/Scripts/python.exe -m pytest backend/tests/test_new_endpoints.py backend/tests/test_mcp_registry.py backend/tests/test_integrations_import.py -v`
Expected: PASS. (`test_mcp_registry.py` still spawns the kept `demo_server.py`; `test_integrations_import.py` does not reference `add_demo_mcp_server`.)

- [ ] **Step 7: Commit** (code only — `mcp_servers.json` stays unstaged).

```bash
git add backend/app/routes/integrations.py backend/ocd_core/integrations.py backend/tests/test_new_endpoints.py
git commit
```

---

### Task A2: Rename the plugin importlib module-id prefix `aj360_plugin_` → `plugin_`

**Context:** `integrations.py:53` uses `aj360_plugin_<stem>` only as the `importlib.util.spec_from_file_location` module id (an internal `sys.modules` key). Plugin **tool names** come from `getattr(mod, "NAME", f.stem)` (e.g. `"calculator"`), and dispatch (`run_tool` → `run_plugin`, integrations.py:387-392) matches on `NAME`, never on this prefix. So the rename is cosmetic; the test below proves dispatch is unaffected.

**Files:**
- Test: `backend/tests/test_plugins_dispatch.py` *(new)*
- Modify: `backend/ocd_core/integrations.py:52-53`

- [ ] **Step 1: Write the failing test.** Create `backend/tests/test_plugins_dispatch.py`:

```python
"""Plugin dispatch resolves by NAME, independent of the internal importlib
module-id prefix. Locks in that renaming that prefix cannot break dispatch."""
from ocd_core import integrations


def test_calculator_plugin_dispatches():
    out = integrations.run_tool("calculator", {"expression": "2*(3+4)"})
    assert out == "2*(3+4) = 14"


def test_plugin_module_id_is_not_branded():
    # The internal importlib module id must not carry AJ360 branding.
    import inspect
    src = inspect.getsource(integrations._load_plugin_module)
    assert "aj360_plugin_" not in src
    assert "plugin_" in src
```

- [ ] **Step 2: Run it — expect FAIL on the branding assertion.**

Run: `./venv312/Scripts/python.exe -m pytest backend/tests/test_plugins_dispatch.py -v`
Expected: `test_calculator_plugin_dispatches` PASSES already; `test_plugin_module_id_is_not_branded` FAILS (`aj360_plugin_` still present).

- [ ] **Step 3: Rename the prefix.** In `backend/ocd_core/integrations.py`, change lines 52-53:

```python
        spec = importlib.util.spec_from_file_location(
            f"plugin_{path.stem}", path)
```

- [ ] **Step 4: Run — expect PASS.**

Run: `./venv312/Scripts/python.exe -m pytest backend/tests/test_plugins_dispatch.py -v`
Expected: both PASS.

- [ ] **Step 5: Commit.**

```bash
git add backend/ocd_core/integrations.py backend/tests/test_plugins_dispatch.py
git commit
```

---

### Task A3: De-brand the frontend surface + remove the demo one-click

**Files:**
- Modify: `frontend/ocd_app/state.py:168`, `:283-296`
- Modify: `frontend/ocd_app/api_client.py:250-251`
- Modify: `frontend/ocd_app/components/composer.py:113-114`, `:129`
- Modify: `frontend/ocd_app/ocd_app.py:1`

- [ ] **Step 1: Remove the demo state handler.** In `frontend/ocd_app/state.py`, delete the entire `add_demo_mcp` method (lines 283-295, through its final `yield`):

```python
    async def add_demo_mcp(self):
        """Register the bundled, secret-free demo MCP server (one click)."""
        self.mcp_status = "Connecting to demo MCP server…"
        yield
        item = await api_client.add_demo_mcp_server()
        await self.load_mcp_servers()
        if item.get("status") == "connected":
            self.enabled_mcp = [*[x for x in self.enabled_mcp if x != item["id"]],
                                item["id"]]
            self.mcp_status = f"Connected · {item.get('detail', '')}"
        else:
            self.mcp_status = f"Failed: {item.get('detail', 'unknown error')}"
        yield
```

- [ ] **Step 2: De-brand the BigQuery comment.** In `frontend/ocd_app/state.py:168`, change:

```python
    bigquery_on: bool = False             # optional BigQuery capability, default OFF
```

- [ ] **Step 3: Remove the client helper.** In `frontend/ocd_app/api_client.py`, delete `add_demo_mcp_server` (lines 250-251):

```python
async def add_demo_mcp_server() -> dict:
    return await _post("\mcp-servers\demo")  # type: ignore[return-value]
```

- [ ] **Step 4: Remove the composer menu item + de-brand the toggle label.** In `frontend/ocd_app/components/composer.py`, delete lines 113-114:

```python
                    rx.menu.item(rx.icon("plug", size=14), "Add demo MCP server",
                                 on_click=AppState.add_demo_mcp),
```

and change line 129 (the built-in tool row label):

```python
                    _builtin_tool_item("database", "BigQuery",
                                       AppState.bigquery_on, AppState.toggle_bigquery),
```

- [ ] **Step 5: De-brand the module docstring.** In `frontend/ocd_app/ocd_app.py:1`, change the first docstring line:

```python
"""Open Claude Desktop — Projects UI built in Reflex (Claude-Desktop-style workspace).
```

- [ ] **Step 6: Verify syntax + no stale references.**

Run:
```bash
./venv312/Scripts/python.exe -m py_compile frontend/ocd_app/state.py frontend/ocd_app/api_client.py frontend/ocd_app/components/composer.py frontend/ocd_app/ocd_app.py
```
Expected: no output (all compile).

Then confirm nothing still references the removed members or the old label:
```bash
grep -rn "add_demo_mcp\|BigQuery (AJ360)" frontend/ocd_app
```
Expected: no matches.

- [ ] **Step 7: Run the frontend client tests (guard against import breakage).**

Run: `cd frontend && "../venv312/Scripts/python.exe" -m pytest tests/test_api_client.py -v`
Expected: PASS (these do not use `add_demo_mcp_server`).

- [ ] **Step 8: Commit.**

```bash
git add frontend/ocd_app/state.py frontend/ocd_app/api_client.py frontend/ocd_app/components/composer.py frontend/ocd_app/ocd_app.py
git commit
```

---

# Sub-project B — Google-only auth (any Google account)

### Task B1: New `google_oauth.py` helper + dependency

**Files:**
- Modify: `backend/pyproject.toml:19`
- Create: `backend/ocd_core/google_oauth.py`
- Test: `backend/tests/test_google_oauth.py`

- [ ] **Step 1: Add the dependency + install it.** In `backend/pyproject.toml`, add `"google-auth-oauthlib",` right after `"google-auth",` (line 19):

```toml
  "google-auth",
  "google-auth-oauthlib",
```

Then install into the venv (pulls `requests-oauthlib`/`oauthlib`/`requests`; touches no pyjwt pin):

Run: `./venv312/Scripts/python.exe -m pip install google-auth-oauthlib`
Verify: `./venv312/Scripts/python.exe -c "from google_auth_oauthlib.flow import Flow; from google.oauth2 import id_token; from google.auth.transport import requests; print('OK')"`
Expected: `OK`.

- [ ] **Step 2: Write the failing test.** Create `backend/tests/test_google_oauth.py`:

```python
"""Unit tests for ocd_core.google_oauth — offline (no network, no real Google).
authorization_url() builds a string locally; token exchange + id_token verify
are monkeypatched."""
import importlib
from urllib.parse import parse_qs, urlparse

import pytest


def _fresh(monkeypatch):
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_ID", "cid.apps.googleusercontent.com")
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_SECRET", "secret")
    monkeypatch.setenv("OCD_OAUTH_REDIRECT_URI",
                       "http://localhost:8000/auth/google/callback")
    return importlib.reload(importlib.import_module("ocd_core.google_oauth"))


def test_build_auth_url_registers_one_time_state(monkeypatch):
    go = _fresh(monkeypatch)
    url = go.build_auth_url()
    assert url.startswith("https://accounts.google.com/o/oauth2/auth")
    assert "cid.apps.googleusercontent.com" in url
    assert "redirect_uri=http" in url
    state = parse_qs(urlparse(url).query)["state"][0]
    assert go.consume_state(state) is True    # valid once
    assert go.consume_state(state) is False   # one-time only


def test_consume_unknown_state_is_false(monkeypatch):
    go = _fresh(monkeypatch)
    assert go.consume_state("never-issued") is False


def test_exchange_code_returns_verified_email(monkeypatch):
    go = _fresh(monkeypatch)

    class _Creds:
        id_token = "fake-jwt"

    class _FakeFlow:
        credentials = _Creds()

        def fetch_token(self, code):
            assert code == "auth-code-123"

    monkeypatch.setattr(go, "_flow", lambda: _FakeFlow())
    monkeypatch.setattr(go._id_token, "verify_oauth2_token",
                        lambda tok, req, aud: {"email": "alice@example.com",
                                               "email_verified": True})
    assert go.exchange_code("auth-code-123") == "alice@example.com"


def test_exchange_code_rejects_unverified_email(monkeypatch):
    go = _fresh(monkeypatch)

    class _Creds:
        id_token = "fake-jwt"

    class _FakeFlow:
        credentials = _Creds()

        def fetch_token(self, code):
            pass

    monkeypatch.setattr(go, "_flow", lambda: _FakeFlow())
    monkeypatch.setattr(go._id_token, "verify_oauth2_token",
                        lambda tok, req, aud: {"email": "x@example.com",
                                               "email_verified": False})
    with pytest.raises(ValueError):
        go.exchange_code("auth-code-123")
```

- [ ] **Step 3: Run it — expect FAIL (module missing).**

Run: `./venv312/Scripts/python.exe -m pytest backend/tests/test_google_oauth.py -v`
Expected: FAIL / collection error — `No module named 'ocd_core.google_oauth'`.

- [ ] **Step 4: Implement the helper.** Create `backend/ocd_core/google_oauth.py`:

```python
"""Google OAuth2 (Authorization Code) helper for Open Claude Desktop.

Thin wrapper over google-auth-oauthlib. The backend stores no users: a
successful Google login mints the existing HMAC session token (ocd_core.auth),
which *is* the session. Any Google account with a verified email may sign in
(open register; no allowlist).

Config (read at call time, from .env):
  GOOGLE_OAUTH_CLIENT_ID / GOOGLE_OAUTH_CLIENT_SECRET  — the OAuth Web client
  OCD_OAUTH_REDIRECT_URI  — default http://localhost:8000/auth/google/callback

CSRF `state` is stored in-process (single-worker only — documented limitation).
"""
from __future__ import annotations

import os

from google.auth.transport import requests as _google_requests
from google.oauth2 import id_token as _id_token
from google_auth_oauthlib.flow import Flow

# Google returns `openid` (and reorders) scopes on exchange; relax oauthlib's
# strict scope-equality check. localhost callbacks are plain http, so allow it.
os.environ.setdefault("OAUTHLIB_RELAX_TOKEN_SCOPE", "1")

_SCOPES = [
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
]

# In-process one-time CSRF state store. Single-worker only.
_PENDING_STATES: set[str] = set()


def _client_id() -> str:
    return os.getenv("GOOGLE_OAUTH_CLIENT_ID", "")


def _redirect_uri() -> str:
    return os.getenv("OCD_OAUTH_REDIRECT_URI",
                     "http://localhost:8000/auth/google/callback")


def _flow() -> Flow:
    # Permit http on localhost callbacks (dev). Harmless when the redirect is https.
    if _redirect_uri().startswith("http://"):
        os.environ.setdefault("OAUTHLIB_INSECURE_TRANSPORT", "1")
    client_config = {
        "web": {
            "client_id": _client_id(),
            "client_secret": os.getenv("GOOGLE_OAUTH_CLIENT_SECRET", ""),
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
        }
    }
    flow = Flow.from_client_config(client_config, scopes=_SCOPES)
    flow.redirect_uri = _redirect_uri()
    return flow


def build_auth_url() -> str:
    """Create an authorization URL, register its one-time CSRF state, return the URL."""
    flow = _flow()
    url, state = flow.authorization_url(
        access_type="offline", prompt="select_account",
        include_granted_scopes="true")
    _PENDING_STATES.add(state)
    return url


def consume_state(state: str) -> bool:
    """Validate + consume a one-time CSRF state. True iff it was pending."""
    try:
        _PENDING_STATES.remove(state)
        return True
    except KeyError:
        return False


def exchange_code(code: str) -> str:
    """Exchange an auth code for tokens, verify the returned id_token, and return
    the verified email. Raises ValueError when the email is missing/unverified."""
    flow = _flow()
    flow.fetch_token(code=code)
    info = _id_token.verify_oauth2_token(
        flow.credentials.id_token, _google_requests.Request(), _client_id())
    email = info.get("email")
    if not email or not info.get("email_verified"):
        raise ValueError("Google account has no verified email.")
    return email
```

- [ ] **Step 5: Run — expect PASS.**

Run: `./venv312/Scripts/python.exe -m pytest backend/tests/test_google_oauth.py -v`
Expected: 4 PASS.

- [ ] **Step 6: Commit.**

```bash
git add backend/pyproject.toml backend/ocd_core/google_oauth.py backend/tests/test_google_oauth.py
git commit
```

---

### Task B2: Backend routes — Google login + callback; drop `LoginRequest`/`TokenResponse`

**Files:**
- Create: `backend/tests/test_auth_google_routes.py`
- Modify: `backend/app/routes/auth.py` (full replace)
- Modify: `backend/app/schemas.py:6-12`

- [ ] **Step 1: Write the failing test.** Create `backend/tests/test_auth_google_routes.py`:

```python
"""Route tests for Google OAuth login/callback. No real Google: the state store
is seeded directly and exchange_code/build_auth_url are monkeypatched."""
import time

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("APP_AUTH_SECRET", "test-secret")
    monkeypatch.setenv("OCD_FRONTEND_URL", "http://localhost:3000")
    from backend.app.main import app
    return TestClient(app)


def test_login_redirects_to_google(client, monkeypatch):
    from ocd_core import google_oauth
    monkeypatch.setattr(google_oauth, "build_auth_url",
                        lambda: "https://accounts.google.com/o/oauth2/auth?x=1")
    r = client.get("/auth/google/login", follow_redirects=False)
    assert r.status_code in (302, 307)
    assert r.headers["location"].startswith("https://accounts.google.com/")


def test_callback_mints_token_and_redirects(client, monkeypatch):
    from ocd_core import auth, google_oauth
    google_oauth._PENDING_STATES.add("st8")
    monkeypatch.setattr(google_oauth, "exchange_code", lambda code: "alice@example.com")
    r = client.get("/auth/google/callback?code=abc&state=st8", follow_redirects=False)
    assert r.status_code in (302, 307)
    loc = r.headers["location"]
    assert loc.startswith("http://localhost:3000/auth/complete?token=")
    token = loc.split("token=", 1)[1]
    assert auth.decode_token(token) == "alice@example.com"


def test_callback_rejects_bad_state(client, monkeypatch):
    from ocd_core import google_oauth
    monkeypatch.setattr(google_oauth, "exchange_code", lambda code: "x@example.com")
    r = client.get("/auth/google/callback?code=abc&state=UNKNOWN", follow_redirects=False)
    assert r.headers["location"] == "http://localhost:3000/login?error=auth_failed"


def test_callback_handles_exchange_failure(client, monkeypatch):
    from ocd_core import google_oauth
    google_oauth._PENDING_STATES.add("st9")

    def _boom(code):
        raise ValueError("bad code")

    monkeypatch.setattr(google_oauth, "exchange_code", _boom)
    r = client.get("/auth/google/callback?code=abc&state=st9", follow_redirects=False)
    assert r.headers["location"] == "http://localhost:3000/login?error=auth_failed"
```

- [ ] **Step 2: Run it — expect FAIL (routes are still `/auth/login`).**

Run: `./venv312/Scripts/python.exe -m pytest backend/tests/test_auth_google_routes.py -v`
Expected: FAIL (404 on `/auth/google/*`).

- [ ] **Step 3: Replace the routes.** Overwrite `backend/app/routes/auth.py` with:

```python
from __future__ import annotations

import os
import time

from fastapi import APIRouter
from fastapi.responses import RedirectResponse
from ocd_core import auth, google_oauth

router = APIRouter(prefix="/auth")


def _frontend_url() -> str:
    return os.getenv("OCD_FRONTEND_URL", "http://localhost:3000")


@router.get("/google/login")
def google_login() -> RedirectResponse:
    """Kick off the OAuth Authorization-Code flow → redirect to Google consent."""
    return RedirectResponse(google_oauth.build_auth_url())


@router.get("/google/callback")
def google_callback(code: str = "", state: str = "") -> RedirectResponse:
    """Google redirects here. Validate the CSRF state, exchange the code for a
    verified email, mint the HMAC session token, and hand it to the frontend."""
    fe = _frontend_url()
    if not code or not google_oauth.consume_state(state):
        return RedirectResponse(f"{fe}/login?error=auth_failed")
    try:
        email = google_oauth.exchange_code(code)
    except Exception:
        return RedirectResponse(f"{fe}/login?error=auth_failed")
    token = auth.make_token(email, int(time.time()))
    return RedirectResponse(f"{fe}/auth/complete?token={token}")
```

- [ ] **Step 4: Remove the now-unused schemas.** In `backend/app/schemas.py`, delete `LoginRequest` (lines 6-8) and `TokenResponse` (lines 11-12), so the file begins:

```python
from __future__ import annotations

from pydantic import BaseModel


class Message(BaseModel):
    role: str
    content: str
    kind: str = "user"
```

- [ ] **Step 5: Run — expect PASS.**

Run: `./venv312/Scripts/python.exe -m pytest backend/tests/test_auth_google_routes.py -v`
Expected: 4 PASS.

- [ ] **Step 6: Confirm nothing else imports the deleted schemas.**

Run: `grep -rn "LoginRequest\|TokenResponse" backend`
Expected: no matches.

- [ ] **Step 7: Commit.**

```bash
git add backend/app/routes/auth.py backend/app/schemas.py backend/tests/test_auth_google_routes.py
git commit
```

---

### Task B3: Frontend "Sign in with Google" + `/auth/complete`

**Files:**
- Modify: `frontend/ocd_app/auth.py` (replace lines 29-137)
- Modify: `frontend/ocd_app/api_client.py:77-82`
- Modify: `frontend/ocd_app/ocd_app.py:8`, insert after `:27`
- Modify: `frontend/tests/test_api_client.py:17-29`

- [ ] **Step 1: Rewrite the login test.** In `frontend/tests/test_api_client.py`, replace `test_login_returns_token_and_sets_bearer` (lines 17-29) with (keep `test_anonymous_has_no_auth_header` intact — it must still see no token):

```python
@respx.mock
async def test_configure_token_sets_bearer_header():
    api_client.configure(token="tok-123")
    try:
        proj = respx.get("http://test/projects").mock(
            return_value=httpx.Response(200, json=[]))
        await api_client.list_projects()
        assert proj.calls.last.request.headers["authorization"] == "Bearer tok-123"
    finally:
        api_client.configure(token=None)  # don't leak into other tests
```

- [ ] **Step 2: Run it — the new test PASSES (it locks the client contract before we remove `login()`).**

Run: `cd frontend && "../venv312/Scripts/python.exe" -m pytest tests/test_api_client.py -v`
Expected: `test_configure_token_sets_bearer_header` and `test_anonymous_has_no_auth_header` PASS; `test_login_returns_token_and_sets_bearer` no longer exists. (`configure()` already exists, so this is a characterization test, not a red→green step.) If any leftover reference to the removed test fails collection, fix it.

- [ ] **Step 3: Remove `login()` from the client.** In `frontend/ocd_app/api_client.py`, delete the auth section (lines 77-82):

```python
# ----------------------------- auth ----------------------------- #
async def login(username: str, password: str) -> str:
    data = await _post("/auth/login", {"username": username, "password": password})
    token = data["token"]
    configure(token=token)
    return token
```

- [ ] **Step 4: Rewrite the frontend auth module.** In `frontend/ocd_app/auth.py`, replace everything from line 29 (the `from ocd_core.auth import (...)` block) through the end of the file (line 137) with:

```python
# Pure HMAC crypto lives in ocd_core.auth so the FastAPI backend can verify
# tokens without importing Reflex. Imported here for the UI auth gate.
from ocd_core.auth import (  # noqa: F401
    auth_enabled,
    make_token,
    verify_token,
)

from . import api_client

# Session lifetime (seconds). Default 7 days; override with AUTH_SESSION_TTL_SEC.
_TTL = int(os.getenv("AUTH_SESSION_TTL_SEC", str(7 * 24 * 3600)))
_COOKIE = "ocd_auth"


if not auth_enabled():
    print("[AUTH] WARNING: Reflex app auth is DISABLED (set GOOGLE_OAUTH_CLIENT_ID, "
          "GOOGLE_OAUTH_CLIENT_SECRET and APP_AUTH_SECRET to enable the login gate).",
          file=sys.stderr)


# --------------------------------------------------------------------------- #
#  Auth state
# --------------------------------------------------------------------------- #
class AuthState(rx.State):
    auth_token: str = rx.Cookie("", name=_COOKIE, max_age=_TTL, same_site="lax")

    @rx.var
    def is_authenticated(self) -> bool:
        """For UI conditionals (e.g. showing a logout button)."""
        if not auth_enabled():
            return True  # auth disabled => open (local dev)
        return verify_token(self.auth_token, int(time.time()))

    @rx.event
    def require_login(self):
        """FIRST on_load handler on every gated page. Applies the cookie token to
        the API client, then verifies it freshly (not via a cached computed var)
        so expiry is always enforced."""
        if self.auth_token:
            api_client.configure(token=self.auth_token)
        if auth_enabled() and not verify_token(self.auth_token, int(time.time())):
            return rx.redirect("/login")

    @rx.event
    def redirect_if_authed(self):
        """on_load for /login: skip the sign-in button if already signed in."""
        if auth_enabled() and verify_token(self.auth_token, int(time.time())):
            return rx.redirect("/")

    @rx.event
    def complete_login(self):
        """on_load for /auth/complete: read ?token= (minted by the backend after
        Google verified the email), persist it in the cookie, apply it to the API
        client, and land on the home page. No token => back to /login."""
        token = ""
        try:
            token = self.router.page.params.get("token", "")
        except Exception:
            token = ""
        if not token:
            return rx.redirect("/login")
        self.auth_token = token
        api_client.configure(token=token)
        return rx.redirect("/")

    @rx.event
    def do_logout(self):
        self.auth_token = ""
        api_client.configure(token=None)
        return rx.redirect("/login")


# --------------------------------------------------------------------------- #
#  Pages
# --------------------------------------------------------------------------- #
def login_page() -> rx.Component:
    return rx.center(
        rx.card(
            rx.vstack(
                rx.hstack(
                    rx.icon("lock", size=20),
                    rx.heading("Open Claude Desktop", size="5"),
                    spacing="2", align="center",
                ),
                rx.text("Sign in to continue", size="2", color="var(--gray-9)"),
                rx.link(
                    rx.button(
                        rx.icon("log-in", size=18),
                        "Sign in with Google",
                        size="3", width="100%",
                    ),
                    href=f"{api_client._BASE}/auth/google/login",
                    width="100%",
                ),
                spacing="3", width="320px",
            ),
            padding="28px",
        ),
        height="100vh", width="100%", background="var(--gray-1)",
    )


def complete_page() -> rx.Component:
    return rx.center(
        rx.vstack(
            rx.spinner(size="3"),
            rx.text("Signing you in…", size="2", color="var(--gray-9)"),
            spacing="3", align="center",
        ),
        height="100vh", width="100%", background="var(--gray-1)",
    )
```

Also update the module docstring at the top of `frontend/ocd_app/auth.py` (lines 1-18) so it no longer describes username/password — replace the `Behaviour:` bullet list with a Google description. Minimal edit: change the first sentence block to:

```python
"""Authentication gate for the Open Claude Desktop Reflex app.

Sign-in is Google-only ("Sign in with Google"): the backend runs the OAuth
Authorization-Code flow, verifies the Google email, and mints the shared HMAC
session token (ocd_core.auth). This module gates pages on that token.

Behaviour:
  * If GOOGLE_OAUTH_CLIENT_ID, GOOGLE_OAUTH_CLIENT_SECRET and a signing secret
    are all configured, every page is gated: unauthenticated visitors are
    redirected to /login.
  * If they are NOT configured, auth is treated as disabled (open) and a
    warning is emitted at import time.

Token format (opaque to the client): base64url("<user>|<exp>|<hmac_sha256>").
"""
```

(Keep the existing `import os`, `import sys`, `import time`, `import reflex as rx` lines at 19-25.)

- [ ] **Step 5: Register the `/auth/complete` page.** In `frontend/ocd_app/ocd_app.py`, change the auth import (line 8):

```python
from .auth import AuthState, complete_page, login_page
```

and insert a new page registration immediately after the `/login` registration (after line 27):

```python
app.add_page(complete_page, route="/auth/complete", on_load=AuthState.complete_login,
             title="Open Claude Desktop · Signing in")
```

- [ ] **Step 6: Verify syntax + no stale references.**

Run:
```bash
./venv312/Scripts/python.exe -m py_compile frontend/ocd_app/auth.py frontend/ocd_app/api_client.py frontend/ocd_app/ocd_app.py
grep -rn "AuthState.username\|AuthState.password\|AuthState.do_login\|AuthState.set_username\|AuthState.set_password\|AuthState.error\|api_client.login\|credentials_ok" frontend/ocd_app
```
Expected: py_compile silent; grep returns no matches (all removed members are gone from callers). If the grep finds a reference (e.g. a stray `AuthState.error` in a component), remove it.

- [ ] **Step 7: Run the frontend client tests — expect PASS.**

Run: `cd frontend && "../venv312/Scripts/python.exe" -m pytest tests/test_api_client.py -v`
Expected: PASS.

- [ ] **Step 8: Commit.**

```bash
git add frontend/ocd_app/auth.py frontend/ocd_app/api_client.py frontend/ocd_app/ocd_app.py frontend/tests/test_api_client.py
git commit
```

---

### Task B4: Backend `auth.py` — Google-keyed `auth_enabled()`; remove `credentials_ok`

**Files:**
- Modify: `backend/ocd_core/auth.py:36-46`, `:90-96`
- Modify: `backend/tests/test_ocd_auth.py`
- Modify: `backend/tests/test_app_health_auth.py`
- Delete: `tests/test_auth.py` (legacy — loads the deleted `aj360_app/aj360_app/auth.py`)

- [ ] **Step 1: Update the unit tests first (TDD).** In `backend/tests/test_ocd_auth.py`:
  - Delete `test_credentials_ok` (lines 35-41).
  - Replace `test_auth_disabled_when_unset` (lines 44-51) with a version that also clears the Google vars, and add a "Google enables it" test:

```python
def test_auth_disabled_when_unset(monkeypatch):
    for k in ("APP_USERNAME", "APP_PASSWORD", "CHAINLIT_AUTH_SECRET",
              "AJ360_AUTH_SECRET", "APP_AUTH_SECRET",
              "GOOGLE_OAUTH_CLIENT_ID", "GOOGLE_OAUTH_CLIENT_SECRET"):
        monkeypatch.delenv(k, raising=False)
    a = importlib.reload(importlib.import_module("ocd_core.auth"))
    assert a.auth_enabled() is False


def test_auth_enabled_with_google(monkeypatch):
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_ID", "cid")
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_SECRET", "sec")
    monkeypatch.setenv("APP_AUTH_SECRET", "s")
    a = importlib.reload(importlib.import_module("ocd_core.auth"))
    assert a.auth_enabled() is True
```

  (Leave `test_token_roundtrip_and_tamper`, `test_decode_token_returns_username`, and `test_app_auth_secret_preferred_over_chainlit` unchanged — `make_token`/`decode_token`/`verify_token`/`_secret` are unchanged.)

- [ ] **Step 2: Rewrite the protected-route test.** In `backend/tests/test_app_health_auth.py`, replace `test_auth_disabled_allows_unauthed` (lines 16-20) and `test_login_and_protected_route` (lines 23-33) with:

```python
def test_auth_disabled_allows_unauthed(client, monkeypatch):
    for k in ("APP_USERNAME", "APP_PASSWORD", "APP_AUTH_SECRET",
              "CHAINLIT_AUTH_SECRET", "AJ360_AUTH_SECRET",
              "GOOGLE_OAUTH_CLIENT_ID", "GOOGLE_OAUTH_CLIENT_SECRET"):
        monkeypatch.delenv(k, raising=False)
    r = client.get("/settings")
    assert r.status_code == 200


def test_protected_route_requires_valid_token(monkeypatch):
    import time

    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_ID", "cid")
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_SECRET", "sec")
    monkeypatch.setenv("APP_AUTH_SECRET", "s")
    from ocd_core import auth
    from backend.app.main import app
    c = TestClient(app)
    assert c.get("/settings").status_code == 401                     # no token
    tok = auth.make_token("alice@example.com", int(time.time()))
    r = c.get("/settings", headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 200
    assert c.get("/settings",
                 headers={"Authorization": "Bearer garbage"}).status_code == 401
```

- [ ] **Step 3: Run the tests — expect FAIL.**

Run: `./venv312/Scripts/python.exe -m pytest backend/tests/test_ocd_auth.py backend/tests/test_app_health_auth.py -v`
Expected: FAIL — `test_credentials_ok` removed but `auth_enabled()` still keys on `APP_USERNAME/APP_PASSWORD`, so `test_auth_enabled_with_google` FAILS (Google vars don't enable it yet).

- [ ] **Step 4: Update `backend/ocd_core/auth.py`.** Remove `_expected_user` (lines 36-37), `_expected_pass` (lines 40-41), and `credentials_ok` (lines 90-96). Replace `auth_enabled` (lines 44-46) with:

```python
def auth_enabled() -> bool:
    """True only when Google OAuth client credentials AND a signing secret are
    all configured. Unconfigured -> open (local dev), matching prior behaviour."""
    return bool(os.getenv("GOOGLE_OAUTH_CLIENT_ID")
                and os.getenv("GOOGLE_OAUTH_CLIENT_SECRET")
                and _secret())
```

Also update the module docstring (lines 1-17): drop the sentence about re-importing `credentials_ok` and about `APP_USERNAME/APP_PASSWORD`; state that identity now comes from Google OAuth (`ocd_core.google_oauth`) and this module only mints/verifies the session token.

- [ ] **Step 5: Delete the legacy root test.** Remove `tests/test_auth.py` (it loads `aj360_app/aj360_app/auth.py`, deleted during the earlier rename, and tests the removed `credentials_ok`). It is superseded by `backend/tests/test_ocd_auth.py`.

```bash
git rm tests/test_auth.py
```

- [ ] **Step 6: Run the full backend auth suite — expect PASS.**

Run: `./venv312/Scripts/python.exe -m pytest backend/tests/test_ocd_auth.py backend/tests/test_app_health_auth.py backend/tests/test_auth_google_routes.py -v`
Expected: all PASS.

- [ ] **Step 7: Confirm no lingering references to removed names.**

Run: `grep -rn "credentials_ok\|_expected_user\|_expected_pass" backend frontend`
Expected: no matches.

- [ ] **Step 8: Commit.**

```bash
git add backend/ocd_core/auth.py backend/tests/test_ocd_auth.py backend/tests/test_app_health_auth.py
git commit
```

---

### Task B5: `.env.example` + `SECURITY.md` + setup docs

**Files:**
- Modify: `.env.example:24-26`
- Modify: `SECURITY.md:22`, `:32`

- [ ] **Step 1: Update `.env.example`.** Replace the auth block (currently `CHAINLIT_AUTH_SECRET` / `APP_USERNAME` / `APP_PASSWORD`, lines 24-26) with:

```dotenv
# --- Session signing secret (REQUIRED to enable auth) ---
# Generate one, e.g.:  python -c "import secrets; print(secrets.token_urlsafe(48))"
APP_AUTH_SECRET=paste_generated_secret_here   # CHAINLIT_AUTH_SECRET also accepted (back-compat)

# --- Google OAuth ("Sign in with Google") ---
# Create a Web OAuth client in Google Cloud Console (see docs), then paste both:
GOOGLE_OAUTH_CLIENT_ID=your_client_id.apps.googleusercontent.com
GOOGLE_OAUTH_CLIENT_SECRET=your_client_secret
# Must EXACTLY match an Authorized redirect URI on the OAuth client:
OCD_OAUTH_REDIRECT_URI=http://localhost:8000/auth/google/callback
# Where the backend sends the browser back after login:
OCD_FRONTEND_URL=http://localhost:3000

# DEPRECATED — username/password auth was removed; these are ignored:
# APP_USERNAME=...
# APP_PASSWORD=...
```

- [ ] **Step 2: Update `SECURITY.md`.** At line 22, change the auth-gate description from `APP_USERNAME` / `APP_PASSWORD` / `CHAINLIT_AUTH_SECRET` to: "Google OAuth (`GOOGLE_OAUTH_CLIENT_ID` / `GOOGLE_OAUTH_CLIENT_SECRET`) plus a session signing secret (`APP_AUTH_SECRET`, `CHAINLIT_AUTH_SECRET` back-compat)." At line 32, replace `APP_PASSWORD` in the secrets-to-protect list with `GOOGLE_OAUTH_CLIENT_SECRET` and keep `CHAINLIT_AUTH_SECRET`/`APP_AUTH_SECRET`.

- [ ] **Step 3: Verify.**

Run: `grep -n "GOOGLE_OAUTH_CLIENT_ID\|OCD_OAUTH_REDIRECT_URI\|OCD_FRONTEND_URL" .env.example`
Expected: the three keys present.

- [ ] **Step 4: Commit.**

```bash
git add .env.example SECURITY.md
git commit
```

---

## Google Cloud setup steps (for the user — Claude cannot do this)

1. **Google Cloud Console → APIs & Services → OAuth consent screen.** Choose **External**. Add your Google email under **Test users** (or Publish). App name/email as prompted.
2. **APIs & Services → Credentials → Create Credentials → OAuth client ID → Application type: Web application.**
3. Under **Authorized redirect URIs**, add exactly: `http://localhost:8000/auth/google/callback` (must match `OCD_OAUTH_REDIRECT_URI`).
4. Create → copy the **Client ID** and **Client secret** into `.env` as `GOOGLE_OAUTH_CLIENT_ID` / `GOOGLE_OAUTH_CLIENT_SECRET`.
5. Set `APP_AUTH_SECRET` to a random string (see `.env.example`). Restart the backend (from `backend/`) and the Reflex app.
6. With those set, `auth_enabled()` becomes true; every page redirects to `/login`, which shows **Sign in with Google**.

## Manual end-to-end verification (after the user supplies real credentials)

- Visit `http://localhost:3000/` → redirected to `/login` → click **Sign in with Google** → Google consent → back to `/auth/complete?token=…` → lands on `/` authenticated.
- Reload `/` → still authenticated (cookie). Logout → back to `/login`.
- With Google **unset** (local dev), the app stays open (no gate) — unchanged behavior.
- The MCP servers menu has **no "AJ360 Demo"** and no "Add demo MCP server" item; the tools toggle reads **"BigQuery"**; the `calculator` plugin still runs.

## Data flow (auth)

`/` → `require_login` → `/login` → **Sign in with Google** → backend `GET /auth/google/login` → Google consent → backend `GET /auth/google/callback` (validate CSRF state, verify email, mint HMAC token) → `{OCD_FRONTEND_URL}/auth/complete?token=…` (`complete_login` stores cookie + `configure`s client) → `/` authenticated. API calls carry the Bearer token; `current_user` (`app/deps.py`, unchanged) validates it.

---

## Known limitations (documented, not solved here)

- **Single-worker only:** the OAuth CSRF `state` set (`google_oauth._PENDING_STATES`) and the API client's `_TOKEN` live in-process. Multiple backend workers would not share state, and the process-global client token is fine for a single-user desktop app but not for multi-tenant serving. Noted in the spec's boundaries.
- `mcp_servers.json` is app-managed runtime state that is tracked in git; this plan cleans the stale `aj360_demo` entry in the working tree but leaves the file unstaged. A future cleanup could gitignore it.
