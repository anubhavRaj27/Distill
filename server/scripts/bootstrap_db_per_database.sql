-- Run inside each Distill database (distill, distill_test) as a superuser.
-- Idempotent.

-- distill_readonly needs to resolve names in the public schema, and nothing more.
GRANT USAGE ON SCHEMA public TO distill_readonly;

-- Explicitly ensure no blanket table access was inherited from anywhere.
REVOKE ALL ON ALL TABLES IN SCHEMA public FROM distill_readonly;
REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM distill_readonly;
REVOKE CREATE ON SCHEMA public FROM PUBLIC;

-- Per-workspace views are granted to distill_readonly individually, at the moment they are
-- generated, inside the same transaction as the CREATE (see review finding 8.2). There is
-- deliberately NO default privilege grant here: a default grant would hand distill_readonly
-- access to every future table as well, which is precisely the guarantee we are buying.
