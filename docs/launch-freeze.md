# Hosted/Public Launch Freeze

**Status: FROZEN**

The repository remains available for local loopback desktop development and testing.
Hosted, public-network, multi-tenant, and public release operation is not approved.

The executable policy is `HOSTED_PUBLIC_LAUNCH_FROZEN` in
`backend/ocd_core/launchguard.py`. It is intentionally source-controlled and has no
environment-variable bypass. Backend startup and the release workflow both enforce it.

## Allowed during the freeze

- Packaged or source desktop use with the backend bound to loopback.
- Local CLI and backend development on loopback.
- The repository Docker Compose development stack, which publishes only on host
  loopback through the temporary containment proxy, declares
  `OCD_DEPLOYMENT_MODE=development`, and has authentication configured. The
  `OCD_ALLOW_INSECURE_NETWORK` development marker never bypasses authentication.
- Tests, threat modeling, remediation, and internal validation builds that do not
  publish artifacts.

## Prohibited during the freeze

- `OCD_DEPLOYMENT_MODE=hosted` or `public`.
- `OCD_MULTI_TENANT=1`.
- Non-loopback service binding outside the explicit Compose development carve-out.
- Publishing GitHub release artifacts.

## Days 1–3 containment controls

- Remote marketplace sources, stdio MCP child processes, host code execution, and
  scheduled autonomous work default off. Each requires a separate explicit opt-in;
  Cowork defaults to manual approval and tool permissions default to `ask`.
- `OCD_DB_FALLBACK=0` is the default. Primary database probe, schema initialization,
  backup, and migration failures abort startup; the container cannot suppress an
  Alembic failure.
- Authentication is mandatory whenever tenancy is enabled or the backend binds a
  non-loopback interface.
- Direct launches cap request bytes and process-local concurrency. Docker Compose
  additionally routes through `deploy/nginx/containment.conf`, which caps request
  size, per-client connections, and request rate. Bundle uploads stream under the
  shared 25 MiB upload cap.

These are temporary containment backstops, not substitutes for the distributed
identity, quota, WAF, and gateway controls in the launch-freeze exit criteria.

## Exit criteria

The freeze may be lifted only through a reviewed source change after evidence exists
for all applicable P0 controls:

1. Tenant-scoped Cowork, Scheduler, integration, and approval state with negative tests.
2. RBAC for executable integrations and hosted-mode isolation of MCP/plugin execution.
3. SSRF-safe outbound policy for MCP and connector transports.
4. Fail-closed primary database and migration startup behavior.
5. End-to-end durable scheduled execution with crash/retry tests.
6. Distributed request, concurrency, token/cost, upload, and storage quotas.
7. Production telemetry, immutable audit, backup/restore evidence, and rollback runbook.
8. CI, security, load, accessibility, and AI red-team release gates are green.

The review that lifts the freeze must record the test runs and link the approval decision.
