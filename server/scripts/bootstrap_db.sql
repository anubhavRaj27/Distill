-- Sift database bootstrap. Idempotent: safe to run repeatedly.
--
-- Creates two login roles with deliberately different power:
--
--   sift            owns the schema and every table. The application connects as this.
--   sift_readonly   holds SELECT and nothing else. Generated SQL executes as this.
--
-- Why this matters (decision D10): a Postgres view's access to its underlying tables is
-- checked against the VIEW OWNER, not the caller. So sift_readonly can read a per-workspace
-- view owned by sift without holding any privilege on the base tables at all. That makes
-- "generated SQL can only see this one view" an enforced database guarantee rather than an
-- application convention, which is the whole point of the layered defence.

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'sift') THEN
    CREATE ROLE sift LOGIN PASSWORD 'sift';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'sift_readonly') THEN
    CREATE ROLE sift_readonly LOGIN PASSWORD 'sift_readonly';
  END IF;
END
$$;

-- sift_readonly must never create anything, anywhere.
ALTER ROLE sift_readonly NOCREATEDB NOCREATEROLE NOSUPERUSER NOINHERIT;
