# Option A Re-Scope Plan — Local-First, BYOK Desktop

**Status:** proposed re-scope of the GPT-5.6 30-day remediation, aligned to the product's actual identity.
**Decision:** Open Claude Desktop is the **local-first, private, model-agnostic inverse of Claude Desktop**. Real Claude Desktop is a thin native client on Anthropic's hosted **multi-tenant cloud** (conversations, Projects, and Memory live server-side and sync across web/desktop/mobile via the account); the desktop app's only real differentiator is running **local (stdio) MCP servers**. We keep the brain (BYOK) and all durable state **on the user's machine**.

**Consequence:** keep the launch-freeze + defensive hardening; **drop the multi-tenant SaaS rearchitecture** (that is rebuilding claude.ai's server side).

---

## Phase 0 — Trustworthy baseline (BLOCKER: do first)

Nothing else is verifiable until the environment is fixed and the suite completes.

1. **Pin & sync dependencies.** `anthropic` (was declared but uninstalled) and **`mcp`** must be pinned — the code imports `mcp.client.auth.OAuthClientProvider`, which the installed `mcp` lacked. Pin both in `backend/pyproject.toml`; add a CI check that `pip install` + `pytest --collect-only` succeeds.
2. **Reconcile the interpreter.** The `.venv` is Python 3.12 but `uvicorn` runs hit a Python 3.14 global install. Standardize on the venv interpreter for `uvicorn`/`pytest`.
3. **Fix the Windows `os.name` test crash** (audit finding #27) so `pytest` completes instead of aborting mid-run.
4. **Acceptance:** a full `pytest` run *completes* on Windows with a documented pass/fail number; tests requiring node/`npx`/keychain that must be excluded are listed explicitly (no silent skips). This replaces the prior unverifiable "GREEN" claims.

---

## Disposition of the existing containment work (WIP `codex/days-1-3-containment-wip` @ `78c664e`)

| Finding | Disposition | Notes |
|---|---|---|
| Launch freeze / fail-closed on non-loopback (Days 1–3) | ✅ KEEP & finish | Keystone: enforces "local-first, don't self-expose." |
| DB fail-closed (fallback off by default; no migration `\|\| true`) | ✅ KEEP | Keep the loopback-dev SQLite fallback for local runs. |
| SSRF egress policy (#4) | ✅ KEEP & harden | Wired into MCP; close the residual DNS-rebind TOCTOU (pin the validated IP) + IPv4-mapped-IPv6 gap. |
| Prompt-injection egress/DLP (#26) | ✅ KEEP | #1 safety issue for a local agent with files + web. |
| Upload caps + capacity (#12,#13); stop-cancels (#11); per-turn token cap (#10 local) | ✅ KEEP | Your machine, your bill. |
| Artifact CSP (#23); sidecar random-port + authed readiness (#25) | ✅ KEEP | Desktop-specific safety/correctness. |
| Data integrity: FK constraints, atomic conversation CAS, JSON durability (#14,#15,#17) | ✅ KEEP | Cheap corruption/loss prevention. |
| Release CI-gating + signing + dep pinning (#20) | ✅ KEEP | You ship a binary users download. |
| Host-exec container-only/docs (#18); legacy-frontend fix-or-retire (#22) | ✅ KEEP | See Track 6. |
| Workspace SQL tenant tables + RBAC + memberships + two-tenant tests (#1,#2,#3,#8,#9) | ⏸️ SHELVE on wip | A→B head-start only; not merged. One user → workspaces are organization, not a security boundary. |
| Distributed/Redis quotas (#10 hosted); multi-node durable workers (#6) | ⏸️ SHELVE/simplify | Local crash-resilience (turn-count/heartbeat, one machine) is enough. |
| Managed Postgres/backup/PITR/DR; hosted observability/SLOs/metrics (#21); public-infra container hardening (#19); search tsvector (#16) | ❌ DROP unless C | Cloud-platform work; #21 is also a privacy regression for a local app. |

---

## Build tracks (each gets its own subagent-driven TDD plan when scheduled)

1. **Freeze & fail-closed** — verify launchguard/netguard/DB-fail-closed in the WIP hold; add missing tests. (~done)
2. **Local agent safety** — SSRF egress TOCTOU + IPv6 fix; prompt-injection egress/DLP (domain first-contact approval, secret redaction); artifact CSP on every preview + pinned/vendored preview runtimes.
3. **Local resource safety** — streaming upload caps + enforced capacity; "stop" cancels the provider request; per-turn token/step ceiling with a sane default (not 1M); host code-exec container-only outside the signed sidecar.
4. **Desktop reliability & data integrity** — sidecar random free port + readiness authed to the exact spawned process; FK constraints + `ON DELETE`; atomic conversation CAS (`WHERE version=:expected`, 409 on mismatch); durable writes that surface errors instead of swallowing them.
5. **Release & distribution** — gate releases on full CI, pin actions by SHA, lock deps/hashes, sign desktop binaries, SBOM.
6. **Retire the legacy frontend** — the Reflex `frontend/aj360_app` is dead weight for a Tauri product and its auth is broken (#22). One frontend: the desktop app.

**Order:** Phase 0 → 1 → 2 → 3 → 4 → 6 → 5.

---

## Explicit non-goals (do NOT build unless you deliberately choose B or C)

Multi-tenant SQL isolation, RBAC/memberships, adversarial tenant boundaries, distributed/Redis quotas, managed-Postgres + backup/PITR/DR, hosted metrics/tracing/SLOs, multi-node job workers, public-infra container hardening, search-index scaling.

---

## Adopt Claude's memory model (regardless of A/B/C)

Profile-scoped **extracted facts** (not transcripts), **per-project isolated** memory, **periodic background synthesis** — but **per-local-user on this machine**, not per-tenant. Simpler in a local build; matches the original PRD.

---

## Branch strategy

- `codex/days-1-3-containment` (`7169c3e`) — clean pre-containment state; leave as-is.
- `codex/days-1-3-containment-wip` (`78c664e`) — preserved 65-file blob; source for cherry-picking KEEP items; resting place for the SHELVED tenant work.
- **new `hardening/local-first`** off the clean branch — rebuild KEEP items as reviewed, atomic, TDD'd commits; this is what merges to the desktop line.

---

## A→B (future, optional)

If sync/teams are wanted: the **Obsidian model** — local-first by default + *optional* self-hosted sync. Then the shelved tenant work (scoped to trusted users, not adversarial customers) becomes relevant.
