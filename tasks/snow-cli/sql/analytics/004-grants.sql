-- ========================================================================
-- 004-grants.sql   (Snowflake, lab-7)
--
-- The analyst role already reads the mirrored tables through the
-- <TARGET>_ADMIN database role (lab-1); here it gets the analytics layer.
-- ========================================================================

USE ROLE <% ctx.env.MIRROR_ADMIN_ROLE_NAME %>;
USE DATABASE <% ctx.env.DEMO_DATABASE_NAME %>;
USE SCHEMA <% ctx.env.DEMO_SCHEMA_NAME %>;

GRANT SELECT ON DYNAMIC TABLE <% ctx.env.DEMO_DYNAMIC_TABLE_NAME %> TO ROLE <% ctx.env.DEMO_ANALYST_ROLE_NAME %>;
GRANT SELECT ON SEMANTIC VIEW <% ctx.env.DEMO_SEMANTIC_VIEW_NAME %> TO ROLE <% ctx.env.DEMO_ANALYST_ROLE_NAME %>;
GRANT USAGE ON AGENT <% ctx.env.DEMO_AGENT_NAME %> TO ROLE <% ctx.env.DEMO_ANALYST_ROLE_NAME %>;
