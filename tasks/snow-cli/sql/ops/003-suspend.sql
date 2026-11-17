-- ========================================================================
-- 003-suspend.sql   (Snowflake, step 6)
--
-- SUSPEND_MIRROR stops scheduling new apply runs (an in-flight run
-- finishes). Postgres keeps capturing changes, so nothing is lost while the
-- mirror is paused; RESUME_MIRROR picks up where it stopped.
-- ========================================================================

USE ROLE <% ctx.env.MIRROR_ADMIN_ROLE_NAME %>;

CALL SNOWFLAKE.POSTGRES.SUSPEND_MIRROR('<% ctx.env.MIRROR_NAME %>');

SELECT status, refresh_interval
FROM TABLE(SNOWFLAKE.POSTGRES.DESCRIBE_MIRROR('<% ctx.env.MIRROR_NAME %>'));
