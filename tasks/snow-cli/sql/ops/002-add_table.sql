-- ========================================================================
-- 002-add_table.sql   (Snowflake, lab-6)
--
-- The mirror uses table-level scope, so a new Postgres table stays
-- un-mirrored until you add it. Adding a table triggers its initial
-- snapshot (SNAPSHOTTING, then REPLICATING) without touching the others.
-- ========================================================================

USE ROLE <% ctx.env.MIRROR_ADMIN_ROLE_NAME %>;

CALL SNOWFLAKE.POSTGRES.ALTER_MIRROR(
    mirror_name => '<% ctx.env.MIRROR_NAME %>',
    add_tables  => ['<% ctx.env.PG_SCHEMA_NAME %>.maintenance_events']
);

CALL SNOWFLAKE.POSTGRES.LIST_MIRRORED_TABLES('<% ctx.env.MIRROR_NAME %>');
