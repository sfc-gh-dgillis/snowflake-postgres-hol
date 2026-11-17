-- ========================================================================
-- 001-grants.sql   (Snowflake, step 1)
--
-- Grants that managed mirroring needs before CREATE_MIRROR:
--
--  1. The postgres_mirror_admin application role lets a role create, alter,
--     drop, and monitor mirrors. ACCOUNTADMIN grants it, so setup (demo-up /
--     infrastructure-up) runs that grant (`mirror_check.py grant-mirror-admin`),
--     as ACCOUNTADMIN, and step 1's preflight confirms it:
--       GRANT APPLICATION ROLE SNOWFLAKE.POSTGRES_MIRROR_ADMIN
--           TO ROLE <MIRROR_ADMIN_ROLE_NAME>;
--     (The caller must also OWN the source instance.)
--  2. The snowflake application runs the mirror and needs USAGE on the
--     Postgres instance (this file, as the owning role). Never revoke it:
--     active mirrors break without it.
--
-- Note: no CREATE EXTENSION step is needed in Postgres. New instances ship
-- with the required extensions, and CREATE_MIRROR provisions the rest.
-- ========================================================================

USE ROLE <% ctx.env.MIRROR_ADMIN_ROLE_NAME %>;

GRANT USAGE ON POSTGRES INSTANCE "<% ctx.env.PG_INSTANCE_NAME %>" TO APPLICATION SNOWFLAKE;
