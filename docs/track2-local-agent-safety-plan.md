# Track 2 — Local Agent Safety (Option A) — Implementation Plan

> Execute **subagent-driven** with two-stage review (spec → quality) per change, plus an adversarial verify on the security-critical items. Steps use `- [ ]`.

**Goal:** Close the real safety gaps for a *local* agent that touches the user's files, tools, and the web — without the hosted/multi-tenant machinery (Option A).

**Repo/conventions:** `D:\Projects\open-claude-desktop`, branch `codex/days-1-3-containment-wip`. `PY = .venv/Scripts/python.exe` (Python 3.12). Run backend tests from `backend/` (e.g. `../.venv/Scripts/python.exe -m pytest tests/... -q`). TDD: failing test → run-red → implement → run-green → commit.

**Verified environment facts (checked before writing this):** httpx 0.28.1 / httpcore 1.0.9; `httpx.HTTPTransport` has **no** `network_backend` param (must swap the httpcore pool); `_blocked_ip` **already** handles IPv4-mapped IPv6 on Py3.12 (no fix needed there).

---

## Item 1 — Egress DNS-rebind TOCTOU pin  *(start here)*

**The bug.** `egress.assert_public_url(url)` resolves the host with `getaddrinfo` and validates every address — but then `safe_get` and `mcp_httpx_client_factory` hand the **URL** to `httpx`, which **re-resolves the host independently** for the actual socket. A DNS-rebinding attacker returns a public IP during validation and `127.0.0.1` / `169.254.169.254` during the connect. Validation and connection use *different* resolutions → the SSRF guard is bypassable. (This is the residual gap called out in the audit and in the WIP's own `egress.py` docstring claim "validates every DNS answer before a connection is attempted" — which isn't true today because the answer isn't *pinned*.)

**The fix — pin the connection to the validated address.** Resolve+validate **once, at connect time, in the same resolution used for the socket**, so there is no window between check and use.

**Mechanism (verified against httpcore 1.0.9):** a custom network backend whose `connect_tcp(host, port, …)` resolves the host, validates every returned address with the existing `_blocked_ip`, and then connects to a **validated IP** (via `super().connect_tcp(<ip>, port, …)`). TLS `start_tls` still receives the real hostname from httpx, so certificate verification and SNI are correct. Because our backend does both the resolution and the connection, there is no TOCTOU window.

**Files:**
- Modify: `backend/ocd_core/egress.py` — add `_PinnedBackend` (sync, subclassing `httpcore.backends.sync.SyncBackend`) and `_AsyncPinnedBackend` (subclassing `httpcore.backends.anyio.AnyIOBackend`); a helper `_pinned_transport()` / `_pinned_async_transport()` that builds an `httpx.HTTPTransport`/`AsyncHTTPTransport` whose underlying `httpcore` pool uses the pinned backend; wire both into `safe_get` and `mcp_httpx_client_factory`.
- Test: `backend/tests/test_egress_toctou.py`

- [ ] **Step 1 — failing test: the rebinding attack is blocked at connect.**
  Simulate rebinding by monkeypatching the backend's resolver to return a **public** IP on the first call (validation) and a **private** IP on the second (connect); assert the pinned backend raises `EgressBlocked` (or never connects to the private IP), and that a control host resolving to a single public IP connects. Also assert `safe_get` and the MCP client both use the pinned backend (`isinstance(...)` on the transport's pool backend).
  ```python
  # sketch — the implementer verifies the exact httpcore hook names by running red first
  def test_pinned_backend_blocks_rebind(monkeypatch):
      from ocd_core import egress
      seq = iter(["8.8.8.8", "127.0.0.1"])          # validate public, then connect private
      monkeypatch.setattr(egress, "_resolve_ips", lambda host, port: [next(seq)])
      with pytest.raises(egress.EgressBlocked):
          egress._PinnedBackend().connect_tcp("evil.test", 443, timeout=5)
  ```
- [ ] **Step 2 — run red**, confirm it fails for the right reason (`AttributeError`/no `_PinnedBackend`).
- [ ] **Step 3 — implement** `_resolve_ips` (extract the getaddrinfo+validate out of `_resolved_addresses`), `_PinnedBackend.connect_tcp` (resolve→validate every addr→connect to a validated IP; raise `EgressBlocked` if any is blocked), the async twin, and `_pinned_transport()`/`_pinned_async_transport()`; wire into `safe_get` (sync) and `mcp_httpx_client_factory` (async).
- [ ] **Step 4 — run green.**
- [ ] **Step 5 — adversarial verify (subagent):** try to refute — IPv6 answers, multi-A-record hosts, a host that resolves public at validate and private at connect *inside a real httpx request* (not just the unit hook), literal-IP URLs, and TLS-to-a-real-host (e.g. `https://example.com`) still works. Fix anything that survives.
- [ ] **Step 6 — regression:** `test_egress_policy.py`, `test_connector_ssrf.py`, `test_mcp_oauth.py` still green; the MCP OAuth path still connects to legitimate hosts.
- [ ] **Step 7 — commit:** `fix(egress): pin DNS to the validated address (close SSRF rebind TOCTOU)`

**Non-goal for Item 1:** no IPv6-mapped fix (already handled); no egress *policy* changes (allow/deny lists stay as-is).

---

## Item 2 — Prompt-injection egress / DLP  *(outline — detailed before we start it)*

The agent can be driven by injected content (a poisoned doc/page) to exfiltrate local data via `web_fetch`/search/connectors. Deterministic controls to add:
- **Domain first-contact approval:** the first outbound to a new domain in a turn requires user approval (reuses the gated-approval seam we just kept). Approved domains are remembered per session.
- **Secret-pattern redaction:** strip known secret shapes (API keys, tokens, `Authorization`-like values) from outbound bodies/query strings.
- **Protected-context guard:** block outbound query strings/bodies derived from project-KB / conversation secrets (heuristic: high-entropy or verbatim-from-context strings).
- Log every egress policy decision for the local audit trail.

Tests: injected-doc → attempted exfil to attacker domain is gated/blocked; redaction on a token-bearing body; approved domain flows through.

---

## Item 3 — Artifact preview CSP  *(outline — detailed before we start it)*

Model-generated HTML previews (`desktop/src/components/ArtifactPanel.tsx`) render raw model content and pull runtimes from public CDNs — a prompt-injected artifact can exfiltrate displayed data. Fixes:
- Inject a restrictive **CSP** (`default-src 'none'`; no network by default) into *every* preview document, including `kind === "html"`.
- **Vendor pinned** preview runtimes (Mermaid/React) instead of moving-version CDN URLs (also fixes offline + determinism).

Tests (desktop/vitest): a preview with a remote `<img>`/`fetch` is blocked by CSP; previews render offline.

---

## Non-goals (Option A)

No hosted egress proxy / org domain allowlists as a *service*, no centralized DLP pipeline, no per-tenant policy — those are Option-C. Everything here is local, deterministic, and on by default for the single user.

## Review process (per item)

Fresh implementer subagent → **spec-compliance review** → **code-quality review** → (Item 1 also) **adversarial verify** → commit. Same rigor as Phase 0.
