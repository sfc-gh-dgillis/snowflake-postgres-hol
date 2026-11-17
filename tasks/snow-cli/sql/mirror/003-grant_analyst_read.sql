-- ========================================================================
-- 003-grant_analyst_read.sql   (Snowflake, step 1)
--
-- Reading mirrored data is governed by the <TARGET>_ADMIN database role
-- inside the target database (SELECT on every target table, $changes
-- table, and $live view). CREATE_MIRROR granted it to the mirror's creator
-- WITH GRANT OPTION, so the creator can delegate read access.
-- ========================================================================

USE ROLE <% ctx.env.MIRROR_ADMIN_ROLE_NAME %>;

GRANT DATABASE ROLE <% ctx.env.MIRROR_TARGET_DATABASE_NAME %>.<% ctx.env.MIRROR_TARGET_DATABASE_NAME %>_ADMIN
    TO ROLE <% ctx.env.DEMO_ANALYST_ROLE_NAME %>;
