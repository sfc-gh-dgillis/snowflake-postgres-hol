-- Analyst role.
--
-- Reads mirrored data once lab-1 grants it the mirror's <TARGET>_ADMIN database role
-- (sql/mirror/003-grant_analyst_read.sql; the target database is created by
-- CREATE_MIRROR, so that grant cannot live here), and the lab-7 analytics
-- (iot_mirror_analytics). Granted to the user running the lab so the notebook can switch
-- to it.

DEFINE ROLE {{ analyst_role }}
    COMMENT = 'Reads mirrored IoT data and lab analytics';

-- An account role, not a database role: warehouse privileges cannot go to database roles.
GRANT USAGE ON WAREHOUSE {{ warehouse }} TO ROLE {{ analyst_role }};
GRANT USAGE ON DATABASE {{ lab_database }} TO ROLE {{ analyst_role }};
GRANT USAGE ON SCHEMA {{ lab_database }}.{{ lab_schema }} TO ROLE {{ analyst_role }};

GRANT ROLE {{ analyst_role }} TO USER "{{ setup_user }}";
