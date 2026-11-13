-- The analyst role (defined by iot_mirror_lab) reads the mirrored tables through the
-- <TARGET>_ADMIN database role (lab-1); here it gets the analytics layer. The agent's
-- USAGE grant is in sql/analytics/, with the agent.

GRANT SELECT ON DYNAMIC TABLE {{ lab_database }}.{{ lab_schema }}.{{ dynamic_table }}
    TO ROLE {{ analyst_role }};
GRANT SELECT ON SEMANTIC VIEW {{ lab_database }}.{{ lab_schema }}.{{ semantic_view }}
    TO ROLE {{ analyst_role }};
