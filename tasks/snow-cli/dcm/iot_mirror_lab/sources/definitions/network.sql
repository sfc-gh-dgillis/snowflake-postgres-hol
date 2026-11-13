-- Postgres ingress (create mode only).
--
-- Allows your workstation to reach the lab's Snowflake Postgres instance on port 5432.
-- Postgres instances accept connections only from IPs allowed by a network policy whose
-- rules use MODE = POSTGRES_INGRESS. This policy affects ONLY the Postgres instance, not
-- Snowflake logins.
--
-- pg_allowed_cidr is PG_ALLOWED_CIDR, or AUTO = your current public IP as seen by
-- Snowflake (CURRENT_IP_ADDRESS()/32), resolved by pyutil/dcm/dcm.py before every deploy.
-- Ranges wider than /8 are refused there. `task pg-allow-my-ip` redeploys this project,
-- which updates the rule in place while the policy stays attached.
--
-- Attaching the policy is not a DCM step: pg_instance.py passes NETWORK_POLICY to
-- CREATE POSTGRES INSTANCE, so this project must be deployed before the instance is
-- created. In existing mode the lab never touches your instance's network policy.
--
-- See: https://docs.snowflake.com/en/user-guide/network-policies

{% if instance_mode == 'create' %}
DEFINE NETWORK RULE {{ lab_database }}.{{ lab_schema }}.{{ pg_network_rule }}
    TYPE = IPV4
    MODE = POSTGRES_INGRESS
    VALUE_LIST = ('{{ pg_allowed_cidr }}')
    COMMENT = 'Postgres ingress for the mirror HOL workstation';

DEFINE NETWORK POLICY {{ pg_network_policy }}
    ALLOWED_NETWORK_RULE_LIST = ('{{ lab_database }}.{{ lab_schema }}.{{ pg_network_rule }}')
    COMMENT = 'Postgres ingress policy for the mirror HOL instance';
{% endif %}
