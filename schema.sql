-- ===========================================================================
-- Chainlit 2.11.0 SQLAlchemy data layer schema (PostgreSQL)
-- ---------------------------------------------------------------------------
-- Verified against chainlit==2.11.0 (chainlit/data/sql_alchemy.py). The layer
-- builds INSERT statements dynamically from the live Step/Element dicts, so the
-- tables must contain a SUPERSET of every key that can appear -- including the
-- newer columns (command, defaultOpen, autoCollapse, modes, icon, autoPlay,
-- playerConfig). Missing a column would make inserts fail at runtime.
--
-- Run once:   psql "postgresql://chainlit:PASS@localhost:5432/chainlit" -f schema.sql
-- (docker-compose.yml loads this automatically on first container start.)
--
-- No extension needed: the built-in UUID type is used and Chainlit supplies ids.
-- ===========================================================================

CREATE TABLE IF NOT EXISTS users (
    "id"          UUID PRIMARY KEY,
    "identifier"  TEXT  NOT NULL UNIQUE,
    "metadata"    JSONB NOT NULL DEFAULT '{}'::jsonb,
    "createdAt"   TEXT
);

CREATE TABLE IF NOT EXISTS threads (
    "id"             UUID PRIMARY KEY,
    "createdAt"      TEXT,
    "name"           TEXT,
    "userId"         UUID,
    "userIdentifier" TEXT,
    "tags"           TEXT[],
    "metadata"       JSONB NOT NULL DEFAULT '{}'::jsonb,
    FOREIGN KEY ("userId") REFERENCES users("id") ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS steps (
    "id"            UUID PRIMARY KEY,
    "name"          TEXT NOT NULL,
    "type"          TEXT NOT NULL,
    "threadId"      UUID NOT NULL,
    "parentId"      UUID,
    "streaming"     BOOLEAN NOT NULL DEFAULT FALSE,
    "waitForAnswer" BOOLEAN,
    "isError"       BOOLEAN,
    "metadata"      JSONB DEFAULT '{}'::jsonb,
    "tags"          TEXT[],
    "input"         TEXT,
    "output"        TEXT,
    "createdAt"     TEXT,
    "command"       TEXT,
    "start"         TEXT,
    "end"           TEXT,
    "generation"    JSONB,
    "showInput"     TEXT,
    "defaultOpen"   BOOLEAN,
    "autoCollapse"  BOOLEAN,
    "modes"         TEXT[],
    "icon"          TEXT,
    "language"      TEXT,
    FOREIGN KEY ("threadId") REFERENCES threads("id") ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS elements (
    "id"           UUID PRIMARY KEY,
    "threadId"     UUID,
    "type"         TEXT,
    "url"          TEXT,
    "chainlitKey"  TEXT,
    "name"         TEXT NOT NULL,
    "display"      TEXT,
    "objectKey"    TEXT,
    "size"         TEXT,
    "page"         INT,
    "language"     TEXT,
    "forId"        UUID,
    "mime"         TEXT,
    "props"        JSONB,
    "autoPlay"     BOOLEAN,
    "playerConfig" JSONB,
    FOREIGN KEY ("threadId") REFERENCES threads("id") ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS feedbacks (
    "id"       UUID PRIMARY KEY,
    "forId"    UUID NOT NULL,
    "threadId" UUID NOT NULL,
    "value"    INT  NOT NULL,
    "comment"  TEXT,
    FOREIGN KEY ("threadId") REFERENCES threads("id") ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS ix_threads_user     ON threads("userId");
CREATE INDEX IF NOT EXISTS ix_steps_thread     ON steps("threadId");
CREATE INDEX IF NOT EXISTS ix_elements_thread  ON elements("threadId");
CREATE INDEX IF NOT EXISTS ix_feedbacks_thread ON feedbacks("threadId");
