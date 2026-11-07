-- ========================================================================
-- Lab 1 - Confirm data in Snowflake
--
-- CREATE_MIRROR created the target database with, for each source table:
--   <TABLE>          materialized target table (updated every refresh_interval)
--   <TABLE>$changes  7-day change feed (an Iceberg table written by Postgres)
--   <TABLE>$live     view = target table + changes not yet applied
-- Identifiers are folded to UPPERCASE in Snowflake.
-- ========================================================================

USE ROLE <% ctx.env.MIRROR_ADMIN_ROLE_NAME %>;
USE WAREHOUSE <% ctx.env.DEMO_WAREHOUSE_NAME %>;

CALL SNOWFLAKE.POSTGRES.LIST_MIRRORED_TABLES('<% ctx.env.MIRROR_NAME %>');

SHOW TABLES IN SCHEMA <% ctx.env.MIRROR_TARGET_DATABASE_NAME %>.<% ctx.env.PG_SCHEMA_NAME %>
    ->> SELECT "name", "kind", "is_iceberg", "rows", "change_tracking" FROM $1 ORDER BY "name";

SHOW VIEWS IN SCHEMA <% ctx.env.MIRROR_TARGET_DATABASE_NAME %>.<% ctx.env.PG_SCHEMA_NAME %>
    ->> SELECT "name" FROM $1 ORDER BY "name";

-- Row counts match Postgres: 5 devices, 10 sensors, 485 readings
SELECT 'DEVICES' AS table_name, COUNT(*) AS row_count
FROM <% ctx.env.MIRROR_TARGET_DATABASE_NAME %>.<% ctx.env.PG_SCHEMA_NAME %>.DEVICES
UNION ALL
SELECT 'SENSORS', COUNT(*)
FROM <% ctx.env.MIRROR_TARGET_DATABASE_NAME %>.<% ctx.env.PG_SCHEMA_NAME %>.SENSORS
UNION ALL
SELECT 'READINGS', COUNT(*)
FROM <% ctx.env.MIRROR_TARGET_DATABASE_NAME %>.<% ctx.env.PG_SCHEMA_NAME %>.READINGS;
