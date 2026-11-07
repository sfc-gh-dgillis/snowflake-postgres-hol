-- ========================================================================
-- 002-create_mirror.sql   (Snowflake, lab-1)
--
-- One call sets up the whole pipeline:
--   * in Postgres: a publication, a logical replication slot, and a CDC
--     worker that writes change logs to Iceberg tables through pg_lake
--   * in Snowflake: the target database, one target table per source table
--     plus <table>$changes and <table>$live companions, and a serverless
--     task (APPLY_MIRROR_<mirror_name>) that applies changes every
--     refresh_interval
--
-- target_database must not exist (CREATE_MIRROR creates it) and a name can
-- never be reused. postgres_tables mirrors exactly the tables listed; use
-- postgres_schemas to mirror every current and future table in a schema.
-- target_table_type: SNOWFLAKE (standard tables) or ICEBERG
-- (Snowflake-managed Iceberg tables).
-- ========================================================================

USE ROLE <% ctx.env.MIRROR_ADMIN_ROLE_NAME %>;

CALL SNOWFLAKE.POSTGRES.CREATE_MIRROR(
    mirror_name       => '<% ctx.env.MIRROR_NAME %>',
    postgres_instance => '<% ctx.env.PG_INSTANCE_NAME %>',
    postgres_database => '<% ctx.env.PG_DATABASE_NAME %>',
    target_database   => '<% ctx.env.MIRROR_TARGET_DATABASE_NAME %>',
    postgres_tables   => ['<% ctx.env.PG_SCHEMA_NAME %>.devices',
                          '<% ctx.env.PG_SCHEMA_NAME %>.sensors',
                          '<% ctx.env.PG_SCHEMA_NAME %>.readings'],
    postgres_schemas  => NULL,
    refresh_interval  => '<% ctx.env.MIRROR_REFRESH_INTERVAL %>',
    target_table_type => '<% ctx.env.MIRROR_TARGET_TABLE_TYPE %>'
);
