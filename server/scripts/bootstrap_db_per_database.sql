-- Run inside each Sift database (sift, sift_test) as a superuser.
-- Idempotent.

-- sift_readonly needs to resolve names in the public schema, and nothing more.
GRANT USAGE ON SCHEMA public TO sift_readonly;

-- Explicitly ensure no blanket table access was inherited from anywhere.
REVOKE ALL ON ALL TABLES IN SCHEMA public FROM sift_readonly;
REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM sift_readonly;
REVOKE CREATE ON SCHEMA public FROM PUBLIC;

-- Per-workspace views are granted to sift_readonly individually, at the moment they are
-- generated, inside the same transaction as the CREATE (see review finding 8.2). There is
-- deliberately NO default privilege grant here: a default grant would hand sift_readonly
-- access to every future table as well, which is precisely the guarantee we are buying.
