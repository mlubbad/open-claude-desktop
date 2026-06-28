-- Phase 2: dedicated role + database for ocd_core persistence,
-- separate from Chainlit's "chainlit" DB. Matches the default DATABASE_URL
-- (postgresql+psycopg://ocd:ocd@localhost:5432/ocd). Runs once on first
-- (empty-volume) container start.
CREATE USER ocd WITH PASSWORD 'ocd';
CREATE DATABASE ocd OWNER ocd;
