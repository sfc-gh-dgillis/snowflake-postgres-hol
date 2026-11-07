-- ========================================================================
-- drop_network_policy.sql   (Snowflake teardown, create mode only)
--
-- Run after the Postgres instance is dropped: a network policy that is
-- still attached to an instance cannot be dropped. The network rule lives
-- in the lab database and is dropped with it.
-- ========================================================================

USE ROLE <% ctx.env.MIRROR_ADMIN_ROLE_NAME %>;

DROP NETWORK POLICY IF EXISTS <% ctx.env.PG_NETWORK_POLICY_NAME %>;
