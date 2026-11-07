-- ========================================================================
-- Lab 3 - Verify schema changes in Snowflake
--
-- Expect the new STATUS column and LOCATION renamed to SITE_LOCATION.
-- No mirror reconfiguration was needed: DDL is applied promptly,
-- regardless of refresh_interval.
-- ========================================================================

USE ROLE <% ctx.env.MIRROR_ADMIN_ROLE_NAME %>;
USE WAREHOUSE <% ctx.env.DEMO_WAREHOUSE_NAME %>;

DESCRIBE TABLE <% ctx.env.MIRROR_TARGET_DATABASE_NAME %>.<% ctx.env.PG_SCHEMA_NAME %>.DEVICES
    ->> SELECT "name", "type", "null?" FROM $1;

SELECT *
FROM <% ctx.env.MIRROR_TARGET_DATABASE_NAME %>.<% ctx.env.PG_SCHEMA_NAME %>.DEVICES
ORDER BY DEVICE_ID
LIMIT 20;
