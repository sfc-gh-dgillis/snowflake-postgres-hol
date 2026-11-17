-- ========================================================================
-- 005-restore_refresh_interval.sql   (Snowflake, step 6)
--
-- Return to the configured cadence (MIRROR_REFRESH_INTERVAL).
-- ========================================================================

USE ROLE <% ctx.env.MIRROR_ADMIN_ROLE_NAME %>;

CALL SNOWFLAKE.POSTGRES.ALTER_MIRROR(
    mirror_name      => '<% ctx.env.MIRROR_NAME %>',
    refresh_interval => '<% ctx.env.MIRROR_REFRESH_INTERVAL %>'
);

SELECT status, refresh_interval
FROM TABLE(SNOWFLAKE.POSTGRES.DESCRIBE_MIRROR('<% ctx.env.MIRROR_NAME %>'));
