-- ========================================================================
-- drop_lab_objects.sql   (Snowflake teardown, both modes)
--
-- Drops the lab database (network rule, stage, notebook, dynamic table,
-- semantic view, agent) and the analyst role. Run after the mirror and,
-- in create mode, the network policy are gone.
-- ========================================================================

USE ROLE <% ctx.env.MIRROR_ADMIN_ROLE_NAME %>;

DROP DATABASE IF EXISTS <% ctx.env.DEMO_DATABASE_NAME %>;

DROP ROLE IF EXISTS <% ctx.env.DEMO_ANALYST_ROLE_NAME %>;
