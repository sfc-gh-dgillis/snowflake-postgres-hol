-- ========================================================================
-- 003-verify.sql   (Postgres)
-- Expected on a fresh seed: devices 5, sensors 10, readings 485.
-- ========================================================================

SET search_path TO :"pg_schema";

SELECT 'devices' AS table_name, COUNT(*) AS row_count FROM devices
UNION ALL
SELECT 'sensors', COUNT(*) FROM sensors
UNION ALL
SELECT 'readings', COUNT(*) FROM readings;
