-- Lab foundation: the lab database and schema, the notebook stage, and the warehouse.
--
-- The lab database holds lab-owned objects: the Postgres ingress network rule
-- (network.sql), the notebook and its stage, and the lab-7 analytics (DCM project
-- iot_mirror_analytics, plus the agent created outside DCM). The mirror's target
-- database is NOT defined here: CREATE_MIRROR creates it in lab-1, and it must not
-- exist beforehand.
--
-- ROLES: the project deploys as MIRROR_ADMIN_ROLE_NAME (ACCOUNTADMIN by default) to
-- keep the lab short. A production deployment would own databases, warehouses, and the
-- Postgres instance with SYSADMIN (or a custom role granted to SYSADMIN), use functional
-- roles such as the analyst role (access.sql) for day-to-day work, and reserve
-- ACCOUNTADMIN for account-level setup such as network policies and the
-- postgres_mirror_admin grant.

DEFINE DATABASE {{ lab_database }}
    COMMENT = '{{ lab_database_comment }}';

DEFINE SCHEMA {{ lab_database }}.{{ lab_schema }}
    COMMENT = 'Lab-owned objects: Postgres ingress network rule, notebook, analytics';

DEFINE STAGE {{ lab_database }}.{{ lab_schema }}.{{ lab_stage }}
    DIRECTORY = (ENABLE = TRUE)
    ENCRYPTION = (TYPE = 'SNOWFLAKE_SSE')
    COMMENT = '{{ lab_stage_comment }}';

-- Runs lab queries, the notebook, and the lab-7 dynamic table. The mirror's apply task
-- does NOT use it: apply runs on serverless compute.
--
-- Defined only when the lab owns it (DEMO_WAREHOUSE_MANAGED=true): a purge drops every
-- object the project defines, so an existing warehouse (DEMO_WAREHOUSE_MANAGED=false) is
-- left out and only gets the usage grant in access.sql.
{% if warehouse_managed | string | lower == 'true' %}
DEFINE WAREHOUSE {{ warehouse }}
WITH
    WAREHOUSE_SIZE = 'XSMALL'
    AUTO_SUSPEND = 60
    AUTO_RESUME = TRUE
    INITIALLY_SUSPENDED = TRUE
    COMMENT = 'Warehouse for the Snowflake Postgres mirror HOL';
{% endif %}
