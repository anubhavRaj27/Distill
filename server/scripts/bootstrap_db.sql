-- Distill database bootstrap. Idempotent: safe to run repeatedly.
--
-- Creates two login roles with deliberately different power:
--
--   distill            owns the schema and every table. The application connects as this.
--   distill_readonly   holds SELECT and nothing else. Generated SQL executes as this.
--
-- Why this matters (decision D10): a Postgres view's access to its underlying tables is
-- checked against the VIEW OWNER, not the caller. So distill_readonly can read a per-workspace
-- view owned by distill without holding any privilege on the base tables at all. That makes
-- "generated SQL can only see this one view" an enforced database guarantee rather than an
-- application convention, which is the whole point of the layered defence.

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'distill') THEN
    CREATE ROLE distill LOGIN PASSWORD 'distill';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'distill_readonly') THEN
    CREATE ROLE distill_readonly LOGIN PASSWORD 'distill_readonly';
  END IF;
END
$$;

-- distill_readonly must never create anything, anywhere.
ALTER ROLE distill_readonly NOCREATEDB NOCREATEROLE NOSUPERUSER NOINHERIT;
