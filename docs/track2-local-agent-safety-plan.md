# Track 2 — Local Agent Safety (Option A) — Implementation Plan

> Execute **subagent-driven** with two-stage review (spec → quality) per change, plus an adversarial verify on the security-critical items. Steps use `- [ ]`.

**Goal:** Close the real safety gaps for a *local* agent that touches the user's files, tools, and the web — without the hosted/multi-tenant machinery (Option A).

**Repo/conventions:** `D:\Projects\open-claude-desktop`, branch `codex/days-1-3-containment-wip`. `PY = .venv/Scripts/python.exe` (Python 3.12). Run backend tests from `backend/` (e.g. `../.venv/Scripts/python.exe -m pytest tests/... -q`). TDD: failing test → run-red → implement → run-green → commit.

**Verified environment facts (checked before writing this):** httpx 0.28.1 / httpcore 1.0.9; `httpx.HTTPTransport` has **no** `network_backend` param (must swap the httpcore pool); `_blocked_ip` **already** handles IPv4-mapped IPv6 on Py3.12 (no fix needed there).

---

## Item 1 — Egress DNS-rebind TOCTOU pin  ✅ **DONE** (`7f2de68` + review-fix `024abf4`)

> Shipped: `_resolve_ips` + `_PinnedSyncBackend`/`_PinnedAsyncBackend` + `_PinnedHTTPTransport`/`_PinnedAsyncHTTPTransport`, wired into `safe_get` and `mcp_httpx_client_factory`. Spec review MEETS_SPEC; quality review found + fixed 4 issues (proxy pools fail closed, async DNS off the event loop, stale loopback fixture, `assert`→`raise`); adversarial verify PIN HOLDS across 7 attack classes. **Caveat that seeds Item 2a:** the pin protects only `egress.py`'s own clients — `web_fetch` and `web_search` use raw `httpx` and are still unpinned. Original detailed plan retained below for reference.

### Original plan (Item 1)

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

## Item 2 — Prompt-injection egress / DLP  *(re-scoped after recon — 2026-07-18)*

**Why re-scoped.** Recon of the actual code (not the outline's assumptions) found: (1) **no single egress chokepoint** — `web_fetch` (`integrations.py:1547`) and `web_search` (DDG `httpx.post` `:1318`, SearXNG `httpx.get` `:1334`) use *raw* `httpx` and bypass `egress.py` entirely, so any DLP hook placed only in `egress.py` misses the exact tools injection uses to exfiltrate; (2) **`web_fetch` still carries the Item-1 TOCTOU** — `_blocked_host` resolves once (`:1580`), then `client.stream` re-resolves at connect (`:1583`), on a plain (unpinned) `httpx.Client`; (3) the **approval primitive is fully reusable** (`permissions.PermissionRegistry.wait/resolve` + `approval_required` SSE + `ApprovalPrompt.tsx` — no new UI/route); (4) the outline's **protected-context heuristic is the weak link** — the KB is similarity-only (no enumeration API, `knowledge.py`), entropy/verbatim matching is false-positive-prone, and it isn't Option-A-shaped; but the user's **actual stored secret values** (`secrets.get_secret_store()`) give a *deterministic* redaction target. So: unify the outbound path first, then layer HITL + deterministic redaction, and drop the heuristic.

### Item 2a — Route `web_fetch` + `web_search` through the pinned path  ✅ **DONE** (`65a9d26` + review `7dfa2d4` + bypass fix `0168a92`)

> Shipped: `egress.pinned_client()`; `web_fetch` + DDG on the pinned path; SearXNG redirect-SSRF closed (loopback self-host preserved). Spec review MINOR_GAPS, quality review SHIP_WITH_NITS → fixed (EgressUnavailable so a DNS failure reads as `url_not_accessible` not a policy block; `pinned_client` rejects proxy/mounts; dead `_blocked_host` removed + tests re-homed). Adversarial verify PIN HOLDS across 9 attack classes and found **one real bypass** — CGNAT (100.64/10) via IPv4-mapped IPv6 escaped `_blocked_ip` — now fixed (also retroactively hardens Item 1's clients). 65 egress tests green.

**Goal.** Every agent-triggered outbound HTTP request opens its socket only to a validated IP (close the `web_fetch`/`web_search` DNS-rebind TOCTOU) and passes the egress domain policy — creating the single chokepoint 2b/2c hook into. Completes Item 1 (which fixed only `egress.py`'s clients).

**Files:** modify `backend/ocd_core/egress.py` (add a public pinned-client factory) and `backend/ocd_core/integrations.py` (`web_fetch`, `_ddg_html_results`, `_searxng_results`); new tests `backend/tests/test_egress_web_pin.py`.

- [ ] **1. egress.py — expose a pinned sync client factory.** Add `pinned_client(**kwargs) -> httpx.Client` returning `httpx.Client(transport=_PinnedHTTPTransport(), **kwargs)` (and, if a caller needs streaming, they use `client.stream(...)` on it — the pin is in the transport, so streaming is pinned too). No new backend code; reuse the Item-1 transport.
- [ ] **2. web_fetch (agent-controlled URL) — pin + full policy.** Replace `httpx.Client(...)` at `:1574` with `egress.pinned_client(timeout=15, follow_redirects=False)`; replace each `_blocked_host(hostname)` pre-check (`:1565`, `:1580`) with `egress.assert_public_url(cur)` (supersedes `_blocked_host`: scheme/creds/local-suffix/deny+allow-domains/port allowlist **and** private-IP block), catching `EgressBlocked` → the existing `url_not_allowed` error string. Keep the manual redirect loop, content-type filter, and `_WEB_FETCH_MAX_BYTES` stream cap unchanged. Net: pre-flight policy via `assert_public_url`, connect-time pin via the transport — the same belt-and-suspenders as `safe_get`. **Deliberate tightening to call out:** `assert_public_url` enforces the 80/443 port allowlist (`OCD_EGRESS_ALLOW_PORTS`), so an agent-supplied `:8443` URL is now refused — correct for an agent-fetched URL; note it in the commit.
- [ ] **3. web_search DDG (fixed host) — pin.** Route the `_DDG_URL` POST (`:1318`) through `egress.pinned_client(timeout=15, follow_redirects=False)`; keep the `data={"q": query}` body. DDG is a fixed public host, so this is defense-in-depth/consistency, cheap.
- [ ] **4. web_search SearXNG (user-configured base) — close the redirect-SSRF, but DON'T break local self-host.** Set `follow_redirects=False` on the `:1334` GET (was `True` — a redirect-to-internal SSRF surface on the agent-controlled query; this is the real fix here). **Do NOT** route it through `egress.pinned_client()` and **do NOT** run the base through `assert_public_url`: both block private IPs, which would break a user running SearXNG on `http://127.0.0.1:8888` — a legitimate Option-A setup. The base is *trusted config*, not agent-controlled; the agent controls only the query (goes to the trusted base) and can't force a rebind of the user's own host. So SearXNG stays on a **plain `httpx.Client(follow_redirects=False)`** — the deliberate trusted-config exception to the chokepoint (mirrors the Item-1 loopback-MCP decision). *(A future "pin-to-resolved-IP but allow-private" backend variant could pin it too while keeping loopback; out of scope for 2a.)* Note for 2b/2c: SearXNG is exempt from domain-approval (user's own configured endpoint) but its query should still be redaction-scanned.
- [ ] **5. Tests (`test_egress_web_pin.py`)** — reuse `_dns_sequence` + the `httpcore` `connect_tcp` spy from `test_egress_toctou.py`:
  - `web_fetch` rebind: public-at-validate, private-at-connect → the real backend is never asked to dial the private IP (spy) → returns `url_not_allowed`.
  - `web_fetch` uses a `_PinnedHTTPTransport` (assert the client's transport type via a construction spy).
  - `web_fetch` port tightening: an `https://host:8443/...` URL is refused.
  - SearXNG: a rebind on the base is blocked, **and** a `127.0.0.1` base is still allowed (proves local self-host isn't broken); `follow_redirects=False` on the client.
  - DDG: request goes through the pinned client.
  - Regression: existing `test_web_search.py` (function-level monkeypatch) and `test_connector_ssrf.py` stay green.
- [ ] **6. Adversarial verify (subagent):** try to reach a private IP through `web_fetch`/`web_search` (redirect-chain rebind, IPv6, the SearXNG base, multi-answer DNS) — ground-truth spy on the real backend. Nothing private may connect; local SearXNG base must still work.
- [ ] **7. Commit:** `fix(egress): route web_fetch + web_search through the pinned transport (close SSRF/TOCTOU, unify the outbound chokepoint)`

### Item 2b — First-contact domain approval + egress audit  *(detailed before we start it)*

Reuse `permissions.registry` at the agent loop (`agent.py:1552`, where `turn_id`/`perm_mode` are in scope — the web tools are in `SAFE_TOOLS` and run in `asyncio.to_thread`, so the gate lifts to the loop, not the sync egress fns). First outbound to a new **registrable domain** per session (key on `project_id` — there is no backend `conversation_id`) emits `approval_required` (opaque id = the domain) and `await registry.wait(...)`. Approved domains ride a module-level registry (mirroring `permissions.registry`) or a per-turn `egress_state` dict threaded like `artifact_store` (`agent.py:1271`). Log every decision via `observability.audit({"event":"egress_decision", ...})` — `EgressBlocked` is currently unaudited. Tests copy the `test_agent_hitl.py` registry-poll harness.

### Item 2c — Deterministic outbound redaction  *(detailed before we start it)*

At the 2a chokepoint, redact from outbound body + query + non-allowlisted headers: (1) **known secret VALUES** enumerated from `secrets.get_secret_store()` — zero false positives, these are literally the user's stored keys/tokens; (2) **hardened bare-token patterns** beyond the existing keyword-anchored `_scrub_secrets` (`integrations.py:1493`): `sk-…`, AWS `AKIA…`, GitHub `ghp_…`, JWTs, PEM blocks. Redaction is logged (audit). **Explicitly dropped:** the high-entropy / verbatim-from-KB heuristic (false positives, no KB enumeration API) — revisit under Item 3's data-provenance discussion if ever.

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

Fresh implementer subagent → **spec-compliance review** → **code-quality review** → **adversarial verify** (security-critical items: Item 1 ✅, Item 2a) → commit. Same rigor as Phase 0.
