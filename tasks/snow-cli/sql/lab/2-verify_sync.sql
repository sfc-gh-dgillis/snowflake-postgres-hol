-- ========================================================================
-- Step 2 - Monitor sync in Snowflake
--
-- READINGS (the target table) moves on each refresh_interval; READINGS$live
-- shows new rows within ~30 seconds. apply_lag_seconds is how far the
-- target table trails what Postgres has flushed (0 = caught up).
-- ========================================================================

USE ROLE <% ctx.env.MIRROR_ADMIN_ROLE_NAME %>;
USE WAREHOUSE <% ctx.env.DEMO_WAREHOUSE_NAME %>;

SELECT
    (SELECT COUNT(*) FROM <% ctx.env.MIRROR_TARGET_DATABASE_NAME %>.<% ctx.env.PG_SCHEMA_NAME %>.READINGS) AS readings,
    (SELECT COUNT(*) FROM <% ctx.env.MIRROR_TARGET_DATABASE_NAME %>.<% ctx.env.PG_SCHEMA_NAME %>.READINGS$live) AS readings_live;

SELECT status, refresh_interval, apply_lag_seconds, last_applied_commit_time, last_operation_time
FROM TABLE(SNOWFLAKE.POSTGRES.DESCRIBE_MIRROR('<% ctx.env.MIRROR_NAME %>'));
