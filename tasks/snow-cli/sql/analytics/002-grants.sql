-- ========================================================================
-- 002-grants.sql   (Snowflake, lab-7)
--
-- The analyst role already reads the mirrored tables through the
-- <TARGET>_ADMIN database role (lab-1), and the dynamic table and semantic
-- view through the DCM project iot_mirror_analytics; here it gets the agent,
-- which DCM does not manage.
-- ========================================================================

USE ROLE <% ctx.env.MIRROR_ADMIN_ROLE_NAME %>;
USE DATABASE <% ctx.env.DEMO_DATABASE_NAME %>;
USE SCHEMA <% ctx.env.DEMO_SCHEMA_NAME %>;

GRANT USAGE ON AGENT <% ctx.env.DEMO_AGENT_NAME %> TO ROLE <% ctx.env.DEMO_ANALYST_ROLE_NAME %>;
