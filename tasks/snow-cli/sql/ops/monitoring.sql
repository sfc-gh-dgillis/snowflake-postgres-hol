-- ========================================================================
-- monitoring.sql   (Snowflake, lab-6 and `task mirror-status`)
--
-- Where to look when a mirror misbehaves:
--   * DESCRIBE_MIRROR: status, apply lag, last error (NULL = healthy)
--   * QUERY_ADMIN_LOG: mirror-internal events (INFO, WARN, ERROR, DEBUG)
--   * TASK_HISTORY:    every run of the serverless apply task
--                      APPLY_MIRROR_<mirror_name> (its compute is what you pay for)
-- ========================================================================

USE ROLE <% ctx.env.MIRROR_ADMIN_ROLE_NAME %>;
USE WAREHOUSE <% ctx.env.DEMO_WAREHOUSE_NAME %>;

SELECT status, refresh_interval, apply_lag_seconds, apply_lag_operations,
       last_applied_commit_time, last_operation_time, error_message
FROM TABLE(SNOWFLAKE.POSTGRES.DESCRIBE_MIRROR('<% ctx.env.MIRROR_NAME %>'));

CALL SNOWFLAKE.POSTGRES.QUERY_ADMIN_LOG(
    mirror_name       => '<% ctx.env.MIRROR_NAME %>',
    postgres_instance => '<% ctx.env.PG_INSTANCE_NAME %>',
    level             => 'INFO',
    since_ts          => NULL,
    max_rows          => 20
);

-- Push filters into TASK_HISTORY: its RESULT_LIMIT applies before WHERE
SELECT name, state, scheduled_time, completed_time, error_message
FROM TABLE(SNOWFLAKE.INFORMATION_SCHEMA.TASK_HISTORY(
    SCHEDULED_TIME_RANGE_START => DATEADD('hour', -2, CURRENT_TIMESTAMP()),
    RESULT_LIMIT => 10000
))
WHERE name ILIKE 'APPLY_MIRROR_<% ctx.env.MIRROR_NAME %>'
ORDER BY scheduled_time DESC
LIMIT 20;
