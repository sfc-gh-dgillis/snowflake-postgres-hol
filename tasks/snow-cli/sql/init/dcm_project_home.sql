-- ========================================================================
-- dcm_project_home.sql   (Snowflake, setup)
--
-- Creates the home of the lab's DCM project objects (iot_mirror_lab,
-- iot_mirror_analytics). A DCM project cannot define its own parent database
-- or schema, so this runs as plain SQL before the first `snow dcm create`.
-- UTIL.DCM_PROJECT_ARCHIVE by default, shared with other projects; teardown
-- leaves it in place.
-- ========================================================================

USE ROLE <% ctx.env.MIRROR_ADMIN_ROLE_NAME %>;

CREATE DATABASE IF NOT EXISTS <% ctx.env.DCM_PROJECT_DATABASE %>
    COMMENT = 'Utilities database.';

CREATE SCHEMA IF NOT EXISTS <% ctx.env.DCM_PROJECT_DATABASE %>.<% ctx.env.DCM_PROJECT_SCHEMA %>
    COMMENT = 'DCM project objects.';
