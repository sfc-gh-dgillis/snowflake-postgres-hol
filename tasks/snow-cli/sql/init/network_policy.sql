-- ========================================================================
-- network_policy.sql   (create mode only)
--
-- Allows your workstation to reach the lab's Snowflake Postgres instance on
-- port 5432. Postgres instances accept connections only from IPs allowed by
-- a network policy whose rules use MODE = POSTGRES_INGRESS.
--
-- Creates (or updates) a POSTGRES_INGRESS network rule for one CIDR and a
-- network policy that references it. pg-instance-create attaches the policy
-- to the instance at CREATE time.
--
-- Re-runnable: re-run `task pg-allow-my-ip` whenever your public IP changes
-- (new Wi-Fi, VPN reconnect); the rule is updated in place.
--
-- The CIDR is PG_ALLOWED_CIDR, or AUTO = your current public IP as seen by
-- Snowflake (CURRENT_IP_ADDRESS()/32). Ranges wider than /8 are refused.
-- This policy affects ONLY the Postgres instance, not Snowflake logins.
--
-- See: https://docs.snowflake.com/en/user-guide/network-policies
-- ========================================================================

USE ROLE <% ctx.env.MIRROR_ADMIN_ROLE_NAME %>;
USE DATABASE <% ctx.env.DEMO_DATABASE_NAME %>;
USE SCHEMA <% ctx.env.DEMO_SCHEMA_NAME %>;

EXECUTE IMMEDIATE $$
DECLARE
    my_ip VARCHAR;
    allowed_cidr VARCHAR;
    prefix_length INTEGER;
    not_ipv4 EXCEPTION (-20001, 'CURRENT_IP_ADDRESS() is not IPv4. Set PG_ALLOWED_CIDR in .env/mirror.env to your public IPv4 address with /32.');
    too_wide EXCEPTION (-20002, 'Refusing to open Postgres to a range wider than /8. Set PG_ALLOWED_CIDR to your own IP/32.');
BEGIN
    IF ('<% ctx.env.PG_ALLOWED_CIDR %>' = 'AUTO') THEN
        SELECT CURRENT_IP_ADDRESS() INTO :my_ip;
        IF (CONTAINS(my_ip, ':')) THEN
            RAISE not_ipv4;
        END IF;
        allowed_cidr := my_ip || '/32';
    ELSE
        allowed_cidr := '<% ctx.env.PG_ALLOWED_CIDR %>';
    END IF;

    prefix_length := SPLIT_PART(allowed_cidr, '/', 2)::INTEGER;
    IF (prefix_length < 8) THEN
        RAISE too_wide;
    END IF;

    EXECUTE IMMEDIATE
        'CREATE NETWORK RULE IF NOT EXISTS <% ctx.env.DEMO_DATABASE_NAME %>.<% ctx.env.DEMO_SCHEMA_NAME %>.<% ctx.env.PG_NETWORK_RULE_NAME %>
            TYPE = IPV4
            MODE = POSTGRES_INGRESS
            VALUE_LIST = (''' || :allowed_cidr || ''')
            COMMENT = ''Postgres ingress for the mirror HOL workstation''';

    -- Update in place so re-runs pick up a new IP even while the policy is attached
    EXECUTE IMMEDIATE
        'ALTER NETWORK RULE <% ctx.env.DEMO_DATABASE_NAME %>.<% ctx.env.DEMO_SCHEMA_NAME %>.<% ctx.env.PG_NETWORK_RULE_NAME %>
            SET VALUE_LIST = (''' || :allowed_cidr || ''')';

    EXECUTE IMMEDIATE
        'CREATE NETWORK POLICY IF NOT EXISTS <% ctx.env.PG_NETWORK_POLICY_NAME %>
            ALLOWED_NETWORK_RULE_LIST = (''<% ctx.env.DEMO_DATABASE_NAME %>.<% ctx.env.DEMO_SCHEMA_NAME %>.<% ctx.env.PG_NETWORK_RULE_NAME %>'')
            COMMENT = ''Postgres ingress policy for the mirror HOL instance''';

    RETURN 'Postgres ingress allowed from ' || :allowed_cidr
        || ' via network policy <% ctx.env.PG_NETWORK_POLICY_NAME %>';
END;
$$;

-- ------------------------------------------------------------------------
-- Verify
-- ------------------------------------------------------------------------
SHOW NETWORK POLICIES LIKE '<% ctx.env.PG_NETWORK_POLICY_NAME %>';
DESCRIBE NETWORK RULE <% ctx.env.DEMO_DATABASE_NAME %>.<% ctx.env.DEMO_SCHEMA_NAME %>.<% ctx.env.PG_NETWORK_RULE_NAME %>;
