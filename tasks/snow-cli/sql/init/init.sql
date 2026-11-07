-- ========================================================================
-- init.sql
--
-- Lab foundation: warehouse, lab database / schema / stage, analyst role.
-- The mirror's target database is NOT created here: CREATE_MIRROR creates
-- it in lab-1 (and it must not exist beforehand).
-- ========================================================================

USE ROLE <% ctx.env.MIRROR_ADMIN_ROLE_NAME %>;

-- ========================================================================
-- STEP 1: Warehouse (queries, notebook, lab-7 dynamic table)
-- The mirror's apply task does NOT use it: apply runs on serverless compute.
-- ========================================================================
CREATE WAREHOUSE IF NOT EXISTS <% ctx.env.DEMO_WAREHOUSE_NAME %>
    WAREHOUSE_SIZE = 'XSMALL'
    AUTO_SUSPEND = 60
    AUTO_RESUME = TRUE
    INITIALLY_SUSPENDED = TRUE
    COMMENT = 'Warehouse for the Snowflake Postgres mirror HOL';

-- ========================================================================
-- STEP 2: Lab database and schema
-- Holds lab-owned objects: the Postgres ingress network rule, the notebook
-- and its stage, and the lab-7 analytics objects.
-- ========================================================================
CREATE DATABASE IF NOT EXISTS <% ctx.env.DEMO_DATABASE_NAME %>
    COMMENT = '<% ctx.env.DEMO_DATABASE_DDL_COMMENT %>';

USE DATABASE <% ctx.env.DEMO_DATABASE_NAME %>;

CREATE SCHEMA IF NOT EXISTS <% ctx.env.DEMO_SCHEMA_NAME %>
    COMMENT = 'Lab-owned objects: Postgres ingress network rule, notebook, analytics';

USE SCHEMA <% ctx.env.DEMO_SCHEMA_NAME %>;

-- ========================================================================
-- STEP 3: Internal named stage for notebook artifacts
-- ========================================================================
CREATE STAGE IF NOT EXISTS <% ctx.env.DEMO_INTERNAL_NAMED_STAGE %>
    DIRECTORY = ( ENABLE = TRUE )
    ENCRYPTION = ( TYPE = 'SNOWFLAKE_SSE' )
    COMMENT = '<% ctx.env.DEMO_INTERNAL_NAMED_STAGE_COMMENT %>';

-- ========================================================================
-- STEP 4: Analyst role
-- Reads mirrored data once lab-1 grants it the mirror's <TARGET>_ADMIN
-- database role. Granted to the setup user so the notebook can switch to it.
-- ========================================================================
CREATE ROLE IF NOT EXISTS <% ctx.env.DEMO_ANALYST_ROLE_NAME %>
    COMMENT = 'Reads mirrored IoT data and lab analytics';

GRANT USAGE ON WAREHOUSE <% ctx.env.DEMO_WAREHOUSE_NAME %> TO ROLE <% ctx.env.DEMO_ANALYST_ROLE_NAME %>;
GRANT USAGE ON DATABASE <% ctx.env.DEMO_DATABASE_NAME %> TO ROLE <% ctx.env.DEMO_ANALYST_ROLE_NAME %>;
GRANT USAGE ON SCHEMA <% ctx.env.DEMO_DATABASE_NAME %>.<% ctx.env.DEMO_SCHEMA_NAME %> TO ROLE <% ctx.env.DEMO_ANALYST_ROLE_NAME %>;
GRANT ROLE <% ctx.env.DEMO_ANALYST_ROLE_NAME %> TO USER "<% ctx.env.DEMO_SETUP_USER %>";
