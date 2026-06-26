# Security Policy

## Reporting a vulnerability

Please report security issues privately to the repository owner (open a GitHub
**security advisory** on this repo, or contact the maintainer directly). Do not
open a public issue for security reports.

## Security posture

This project runs an LLM agent against **production BigQuery** and (optionally)
executes model-written code, so several guards are enforced in code:

- **BigQuery is read-only by default.** `app.py` `run_sql` rejects any non-`SELECT`
  statement unless `AJ360_ALLOW_WRITES=true`, and enforces dataset scope against
  BigQuery's parsed `referenced_tables` (not substring matching).
  See `tests/test_sql_guard.py`.
- **Code execution fails shut.** The Reflex `code_execution` tool runs only inside
  a container (`docker --network none`); with no container runtime it refuses
  rather than running on the host. `python` is not in the bash allowlist.
- **Authentication.** Both surfaces require login when credentials are configured
  (`APP_USERNAME` / `APP_PASSWORD` / `CHAINLIT_AUTH_SECRET`). The Reflex app gates
  every page (`tests/test_auth.py`); its backend binds to loopback by default.
- **Credentials.** BigQuery auth uses Application Default Credentials (Workload
  Identity / `gcloud auth application-default login`) — **never** a key file in
  the repo. `.gitignore` is deny-by-default for secrets, and a `gitleaks`
  pre-commit hook + CI job block secret commits.

## Secret rotation

Treat any secret that has touched a working tree as compromised. Rotate the GCP
service account, `ZHIPU_API_KEY`, `APP_PASSWORD`, and `CHAINLIT_AUTH_SECRET` if
there is any chance they were exposed.
