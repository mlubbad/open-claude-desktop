# Security Policy

## Reporting a vulnerability

Please report security issues privately to the repository owner (open a GitHub
**security advisory** on this repo, or contact the maintainer directly). Do not
open a public issue for security reports.

## Security posture

This project runs an LLM agent that can (optionally) query BigQuery and execute
model-written code, so several guards are enforced in code:

- **Hosted/public launch is frozen.** Local loopback desktop development remains
  supported. Hosted, public-network, multi-tenant operation and public release
  publishing fail closed through `backend/ocd_core/launchguard.py`. See
  `docs/launch-freeze.md` for the source-controlled exit criteria.

- **Fail-closed networking.** The backend binds `127.0.0.1` by default and refuses
  to start on a non-loopback interface during the freeze. The development-only
  Compose carve-out requires both `OCD_DEPLOYMENT_MODE=development` and the explicit
  `OCD_ALLOW_INSECURE_NETWORK=1` marker, but authentication remains mandatory for
  every non-loopback bind and whenever tenancy is enabled. See
  `backend/ocd_core/launchguard.py`, `backend/ocd_core/netguard.py`, and their tests.
- **Dangerous capabilities default off.** Remote marketplace sources, stdio MCP,
  host code execution, and scheduled automations require explicit operator opt-ins.
  Cowork starts with manual approval and sensitive tools default to `ask` mode.
- **Database and migration failures are fatal.** `OCD_DB_FALLBACK=0` is the default;
  database reachability, backup, schema, and Alembic failures abort startup rather
  than silently changing persistence or running against a stale schema.
- **Temporary edge limits.** Direct launches cap body size and process concurrency.
  Compose adds Nginx request-size, connection, and request-rate limits; upload routes
  stream under a separate 25 MiB cap. These do not satisfy the distributed production
  quota/WAF exit criterion.
- **Secrets in the OS keychain.** Connector credentials (and provider API keys from
  Phase 1) are stored via `keyring` with an encrypted-file fallback, never plaintext
  in tracked files. See `backend/ocd_core/secrets.py`.
- **BigQuery is read-only by default** (optional connector): `execute_sql` rejects any
  non-`SELECT` statement, enforces a per-project table allowlist on BigQuery's parsed
  `referenced_tables` (not substring matching), and caps bytes billed.
  See `backend/tests/test_sql_guard.py` and `test_execute_sql_guard.py`.
- **Code execution fails shut.** The `code_execution` tool runs only inside a
  container (`docker --network none`); with no container runtime it refuses rather
  than running on the host. `bash` is allowlisted and path-jailed to its sandbox
  (`python` is not allowlisted). See `backend/tests/test_bash_jail.py`.
- **SSRF-guarded fetches.** `web_fetch` and REST connectors block private/internal
  hosts and drop custom auth headers on cross-origin redirects.
  See `backend/tests/test_connector_ssrf.py`.
- **Authentication.** The backend requires a valid bearer token on every request
  when credentials are configured (`APP_USERNAME` / `APP_PASSWORD` /
  `APP_AUTH_SECRET`); login attempts are rate-limited. When unconfigured it runs
  open for local single-user use — which is why the network guard above keeps that
  mode loopback-only.
- **Credentials.** BigQuery auth uses Application Default Credentials (Workload
  Identity / `gcloud auth application-default login`) — **never** a key file in
  the repo. `.gitignore` is deny-by-default for secrets, and a `gitleaks`
  pre-commit hook + CI job block secret commits.

## Secret rotation

Treat any secret that has touched a working tree as compromised. Rotate the GCP
service account, `ZHIPU_API_KEY`, `APP_PASSWORD`, and `CHAINLIT_AUTH_SECRET` if
there is any chance they were exposed.
