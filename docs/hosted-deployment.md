# Hosted deployment & multi-tenancy

VersoWork is **local-first** by default: a single-user BYOK app whose backend is
a loopback HTTP server. The same backend can also run as a **hosted, multi-tenant service**
where each workspace (tenant) is isolated from every other. Multi-tenancy is **off by
default** — with it off, everything below is a no-op and the packaged desktop is byte-for-byte
unchanged.

This guide covers turning it on and the env that a hosted deployment sets. It documents the
tenancy work landed in `ocd_core.tenancy` and `ocd_core.auth`; see `CLAUDE.md` →
*"Workspace tenancy (hosted-SaaS seam)"* for the internal contract.

---

## 1. The switch

```bash
OCD_MULTI_TENANT=1      # enable per-workspace isolation. Unset/0/false = local single-user.
```

When enforcing, every project/conversation read, write, list, and delete — plus keychain
secrets, the settings file, and vector collections — is scoped to the **current workspace**,
resolved per request (see §2). When off, `tenancy.enforcing()` is `False` and all scoping is
a no-op.

### The `local` workspace and zero-migration upgrade

Rows and files written before tenancy was enabled have no workspace tag (`workspace_id IS
NULL`, unprefixed secret keys, the base `settings.json`, the historical collection name).
They all belong to the implicit **`local`** workspace. So a single-user database that later
turns tenancy on keeps working with **no data migration**: its original owner still sees
everything as the `local` workspace, while any *new* workspace sees only what it creates.
Cross-workspace access returns `404` (never revealing that a row exists in another tenant).

---

## 2. Identity → workspace

Each request's workspace is resolved by `tenancy.resolve_workspace`, in this order:

1. **An authenticated bearer token is authoritative.** A valid token resolves to a
   `Principal(user, workspace)`. Its workspace claim scopes the request; if the token carries
   no workspace, the user id is used as a personal workspace. A client **cannot** override
   this with a header — no tenant escape.
2. **`X-OCD-Workspace` header** — only used when there is *no* valid token. For local dev, or
   a trusted reverse proxy that authenticates upstream and injects the workspace.
3. Otherwise → the `local` workspace.

### Auth modes

Auth is off (all requests are the `anonymous`/`local` user) unless one of these is configured:

**Built-in HMAC login** (single operator; carries no workspace):

```bash
APP_USERNAME=...            # login username
APP_PASSWORD=...            # login password
APP_AUTH_SECRET=...         # HMAC signing secret (or CHAINLIT_AUTH_SECRET / OCD_AUTH_SECRET)
AUTH_SESSION_TTL_SEC=604800 # optional; session lifetime, default 7 days
```

**External OIDC / JWT issuer** (the hosted multi-tenant path). The backend verifies tokens
your IdP issues — no PyJWT, no network (JWKS fetch is not yet built; configure the key
directly):

```bash
# One of:
OCD_JWT_SECRET=...          # HS256 shared secret (verified with stdlib hmac)
OCD_JWT_PUBLIC_KEY=...      # RS256 PEM public key (verified with `cryptography`); \n may be escaped

OCD_JWT_ALG=HS256           # the ONLY algorithm accepted (default HS256). The token's own
                            #   `alg` header is never trusted → defeats alg=none / HS-RS confusion.
OCD_JWT_USER_CLAIM=sub      # claim carrying the user id (default `sub`)
OCD_JWT_WORKSPACE_CLAIM=workspace  # claim carrying the tenant/workspace (default `workspace`)
OCD_JWT_ISSUER=...          # optional; if set, `iss` must match
OCD_JWT_AUDIENCE=...        # optional; if set, `aud` must contain it
```

Tokens are rejected (fail-closed) on a bad signature, expiry (`exp`)/not-before (`nbf`), a
mismatched configured algorithm, or a failed issuer/audience check. Clients send the token as
`Authorization: Bearer <jwt>`.

> A hosted deployment must configure auth. `auth.auth_enabled()` becomes true when either mode
> is set, which also lets the backend bind to a non-loopback address (see `netguard`).

---

## 3. What is isolated per workspace

| Surface | Mechanism |
| --- | --- |
| Projects, conversations (+ branching, search, counts) | SQL rows filtered/stamped by `workspace_id` |
| Keychain **secrets** (provider API keys, connector auth, OAuth tokens) | keys namespaced per non-local workspace |
| **Settings** (model/provider/keys/automation config) | `settings.<workspace>.json` beside the base `settings.json` |
| **Vector** collections (project knowledge) | workspace-prefixed collection names (defense-in-depth; already isolated by the globally-unique project slug) |
| **Uploaded files** (project knowledge blobs) | blob keys namespaced per non-local workspace, in whichever object store is configured (§4) |
| Background **Cowork** tasks & **scheduler** automations | each captures its workspace at creation and re-binds it around the whole background run |

For every one of these, the `local` workspace (and flag-off) keeps the historical, unscoped
name — so pre-tenancy data is never stranded.

---

## 4. Other hosted-relevant configuration

```bash
DATABASE_URL=postgresql+psycopg://user:pass@host/db   # a real DB instead of local SQLite
OCD_CORS_ORIGINS=https://app.example.com              # your web origin(s), comma-separated
OCD_ALLOWED_HOSTS=app.example.com                     # Host allowlist (defeats DNS rebinding); "*" disables
SCHEDULER_ENABLED=1                                   # background automation ticker (0 to disable)
```

### Object storage for uploads

Project-knowledge uploads go through a pluggable blob store. **Default (`local`)** is a
transparent filesystem pass-through — the same `projects/<pid>/knowledge/` layout as before,
so the desktop and a single-node server are byte-for-byte unchanged and need no configuration.
For a **multi-node** deploy, point it at an S3-compatible bucket so every node reads the same
uploads; each node keeps an ephemeral local cache (under `.blobcache`) so the path-based text
extractors keep working.

```bash
OCD_BLOB_BACKEND=s3                 # default "local" (filesystem). "s3" enables the bucket backend.
OCD_S3_BUCKET=my-ocd-uploads        # required for the s3 backend
OCD_S3_PREFIX=prod                  # optional key prefix inside the bucket (share one bucket across envs)
OCD_S3_ENDPOINT=https://…           # optional; set for MinIO / Cloudflare R2 / other S3-compatible stores
# AWS credentials come from the standard chain (env / instance role / profile). Needs boto3.
```

Blob keys are workspace-namespaced when tenancy is enforcing (the `local` workspace and flag-off
keep the historical unprefixed key), so two tenants' uploads never collide.

### Durable job queue for background work

Scheduled automations run through a pluggable job queue. **Default (`inprocess`)** runs an
enqueued job immediately in-process — exactly the pre-queue behavior, no config needed. Flip
`OCD_JOB_QUEUE=sql` for a durable, DB-backed queue: enqueued jobs become rows in the shared
database, and each node runs a worker that atomically **claims** a due job under a time-boxed
**lease**, runs it, and marks it done. A worker that dies mid-job lets its lease expire; the
next `reclaim_expired()` returns the job to the queue for another node (at-least-once dispatch).
A `dedup_key` makes two nodes racing to fire the same scheduled occurrence enqueue a single job.

```bash
OCD_JOB_QUEUE=sql          # default "inprocess" (run at enqueue). "sql" = durable DB-backed queue.
# Uses the same DATABASE_URL as everything else — point it at shared Postgres for multi-node.
```

Multi-node caveat: the durable queue makes background *execution* node-independent, but the
schedule *definitions* still live in `schedules.json` on local disk. For more than one node,
put that on a shared volume (or a single ticker node) until it moves into the DB.

`OCD_API_TOKEN` is a **desktop-only** loopback secret (the shell mints it per launch); a hosted
deployment does not set it — use the auth modes in §2 instead.

Network exposure is refused at startup if you bind to a non-loopback address with **no** auth
configured (`netguard`), so a hosted deploy must set an auth mode before it will serve.

---

## 5. Multi-node checklist

The tenancy **isolation** guarantees above are complete, and the two former single-node
constraints now have pluggable answers:

- **Shared Postgres** (`DATABASE_URL`) — projects, conversations, and the durable job queue.
- **Shared object storage** (`OCD_BLOB_BACKEND=s3`, §4) — uploaded knowledge files.
- **Durable job queue** (`OCD_JOB_QUEUE=sql`, §4) — background job execution any node can pick up.
- **Shared schedule store** — put `schedules.json` on a shared volume, or run the ticker on one
  node, until schedule definitions move into the DB.

A single-node deployment needs none of these — the local defaults (SQLite, filesystem, in-process
queue) work out of the box.

---

## 6. Worked example (single-node hosted, OIDC)

```bash
OCD_MULTI_TENANT=1
DATABASE_URL=postgresql+psycopg://ocd:secret@db.internal/ocd
OCD_JWT_PUBLIC_KEY="-----BEGIN PUBLIC KEY-----\n...\n-----END PUBLIC KEY-----"
OCD_JWT_ALG=RS256
OCD_JWT_ISSUER=https://id.example.com/
OCD_JWT_AUDIENCE=open-claude-desktop
OCD_JWT_WORKSPACE_CLAIM=org           # your IdP puts the tenant id in the `org` claim
OCD_CORS_ORIGINS=https://app.example.com
OCD_ALLOWED_HOSTS=api.example.com
```

Your IdP issues `{ "sub": "alice@example.com", "org": "acme", "exp": ... }`; every request
Alice makes is scoped to the `acme` workspace, isolated from every other tenant.
