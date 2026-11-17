-- ========================================================================
-- 004-resume_and_refresh.sql   (Snowflake, step 6)
--
-- RESUME_MIRROR restarts the apply task in place, after checking that the
-- unapplied operations are still on the source (it raises RESTART_REQUIRED
-- if they aged out). REFRESH_MIRROR applies pending changes right away
-- instead of waiting for the next scheduled run.
-- ========================================================================

USE ROLE <% ctx.env.MIRROR_ADMIN_ROLE_NAME %>;

CALL SNOWFLAKE.POSTGRES.RESUME_MIRROR('<% ctx.env.MIRROR_NAME %>');

CALL SNOWFLAKE.POSTGRES.REFRESH_MIRROR('<% ctx.env.MIRROR_NAME %>');

SELECT status, refresh_interval, apply_lag_seconds
FROM TABLE(SNOWFLAKE.POSTGRES.DESCRIBE_MIRROR('<% ctx.env.MIRROR_NAME %>'));
