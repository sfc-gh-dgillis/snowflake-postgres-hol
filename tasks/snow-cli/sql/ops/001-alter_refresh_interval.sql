-- ========================================================================
-- 001-alter_refresh_interval.sql   (Snowflake, step 6)
--
-- ALTER_MIRROR changes the apply cadence in place. A shorter interval keeps
-- the target tables fresher with more, smaller apply runs; a longer one
-- batches more changes per run and costs less. Omitted parameters stay
-- unchanged (do not pass warehouse => NULL unless you mean "serverless").
-- ========================================================================

USE ROLE <% ctx.env.MIRROR_ADMIN_ROLE_NAME %>;

CALL SNOWFLAKE.POSTGRES.ALTER_MIRROR(
    mirror_name      => '<% ctx.env.MIRROR_NAME %>',
    refresh_interval => '<% ctx.env.MIRROR_FAST_REFRESH_INTERVAL %>'
);

SELECT status, refresh_interval
FROM TABLE(SNOWFLAKE.POSTGRES.DESCRIBE_MIRROR('<% ctx.env.MIRROR_NAME %>'));
