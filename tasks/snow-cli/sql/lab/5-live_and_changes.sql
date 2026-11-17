-- ========================================================================
-- Step 5 - Query $live and $changes
--
-- $live: the latest committed Postgres state (~30s behind) on top of the
--        target table, regardless of refresh_interval. Not transactional:
--        it can expose part of a source transaction. Query the target
--        table when you need transactional consistency.
-- $changes: every insert, update, and delete for the last 7 days, with
--        _COMMIT_LSN, _LSN, _XID, _COMMIT_TIME, _CHANGE_TYPE, _IS_UPDATE,
--        and _DATA_VERSION system columns.
-- ========================================================================

USE ROLE <% ctx.env.MIRROR_ADMIN_ROLE_NAME %>;
USE WAREHOUSE <% ctx.env.DEMO_WAREHOUSE_NAME %>;

-- The new device is visible in $live before the next apply run
SELECT *
FROM <% ctx.env.MIRROR_TARGET_DATABASE_NAME %>.<% ctx.env.PG_SCHEMA_NAME %>.DEVICES$live
ORDER BY CREATED_AT DESC
LIMIT 5;

-- A gap between these counts means changes are pending for the next apply run
SELECT
    (SELECT COUNT(*) FROM <% ctx.env.MIRROR_TARGET_DATABASE_NAME %>.<% ctx.env.PG_SCHEMA_NAME %>.DEVICES) AS devices,
    (SELECT COUNT(*) FROM <% ctx.env.MIRROR_TARGET_DATABASE_NAME %>.<% ctx.env.PG_SCHEMA_NAME %>.DEVICES$live) AS devices_live;

-- The UPDATE appears as a delete/insert pair sharing one _XID.
-- (The step 3 column DDL started a fresh DEVICES$changes feed, so only
-- changes made after the rename are listed.)
SELECT _COMMIT_TIME, _XID, _CHANGE_TYPE, _IS_UPDATE, DEVICE_ID, DEVICE_NAME, STATUS
FROM <% ctx.env.MIRROR_TARGET_DATABASE_NAME %>.<% ctx.env.PG_SCHEMA_NAME %>.DEVICES$changes
ORDER BY _COMMIT_LSN, _LSN;

-- Recent row-level changes to READINGS
SELECT _COMMIT_TIME, _CHANGE_TYPE, _IS_UPDATE, READING_ID, SENSOR_ID, VALUE
FROM <% ctx.env.MIRROR_TARGET_DATABASE_NAME %>.<% ctx.env.PG_SCHEMA_NAME %>.READINGS$changes
ORDER BY _COMMIT_LSN DESC, _LSN DESC
LIMIT 20;

-- The deletes from step 4 are in the change feed
SELECT _CHANGE_TYPE, COUNT(*) AS change_rows
FROM <% ctx.env.MIRROR_TARGET_DATABASE_NAME %>.<% ctx.env.PG_SCHEMA_NAME %>.READINGS$changes
GROUP BY _CHANGE_TYPE
ORDER BY _CHANGE_TYPE;
