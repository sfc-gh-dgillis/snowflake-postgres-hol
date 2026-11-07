-- ========================================================================
-- 001-dynamic_table.sql   (Snowflake, lab-7)
--
-- A declarative pipeline on top of the mirror: hourly metrics per site and
-- sensor type, kept fresh automatically. Mirrored target tables have change
-- tracking enabled by CREATE_MIRROR, so the dynamic table can refresh
-- incrementally as the mirror applies Postgres changes.
--
-- End-to-end freshness = mirror refresh_interval + TARGET_LAG.
-- Uses SITE_LOCATION, so run lab-3 (schema changes) first.
-- ========================================================================

USE ROLE <% ctx.env.MIRROR_ADMIN_ROLE_NAME %>;
USE WAREHOUSE <% ctx.env.DEMO_WAREHOUSE_NAME %>;
USE DATABASE <% ctx.env.DEMO_DATABASE_NAME %>;
USE SCHEMA <% ctx.env.DEMO_SCHEMA_NAME %>;

CREATE OR REPLACE DYNAMIC TABLE <% ctx.env.DEMO_DYNAMIC_TABLE_NAME %>
    TARGET_LAG = '1 minute'
    WAREHOUSE = <% ctx.env.DEMO_WAREHOUSE_NAME %>
    REFRESH_MODE = AUTO
    COMMENT = 'Hourly sensor metrics per site, built on tables mirrored from Snowflake Postgres'
AS
SELECT
    d.SITE_LOCATION,
    s.SENSOR_TYPE,
    s.UNIT,
    DATE_TRUNC('hour', r.TS) AS READING_HOUR,
    COUNT(*) AS READING_COUNT,
    AVG(r.VALUE) AS AVG_VALUE,
    MIN(r.VALUE) AS MIN_VALUE,
    MAX(r.VALUE) AS MAX_VALUE
FROM <% ctx.env.MIRROR_TARGET_DATABASE_NAME %>.<% ctx.env.PG_SCHEMA_NAME %>.READINGS r
JOIN <% ctx.env.MIRROR_TARGET_DATABASE_NAME %>.<% ctx.env.PG_SCHEMA_NAME %>.SENSORS s
    ON s.SENSOR_ID = r.SENSOR_ID
JOIN <% ctx.env.MIRROR_TARGET_DATABASE_NAME %>.<% ctx.env.PG_SCHEMA_NAME %>.DEVICES d
    ON d.DEVICE_ID = s.DEVICE_ID
GROUP BY d.SITE_LOCATION, s.SENSOR_TYPE, s.UNIT, DATE_TRUNC('hour', r.TS);

SHOW DYNAMIC TABLES LIKE '<% ctx.env.DEMO_DYNAMIC_TABLE_NAME %>'
    ->> SELECT "name", "target_lag", "refresh_mode", "refresh_mode_reason", "scheduling_state" FROM $1;
