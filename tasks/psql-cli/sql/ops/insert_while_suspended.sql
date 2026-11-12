-- ========================================================================
-- insert_while_suspended.sql   (Postgres, lab-6)
--
-- 100 new readings written while the mirror's apply task is suspended.
-- ========================================================================

SET search_path TO :"pg_schema";

INSERT INTO readings (sensor_id, value, ts)
SELECT
    s.sensor_id,
    CASE WHEN s.sensor_type = 'Temperature'
         THEN (20 + random() * 15)::numeric(10,2)
         ELSE (40 + random() * 50)::numeric(10,2) END,
    NOW()
FROM sensors s
CROSS JOIN generate_series(1, 10)
WHERE s.device_id IN (SELECT device_id FROM devices WHERE device_name <> 'IoT-Gateway-Urgent');

SELECT COUNT(*) AS readings_in_postgres FROM readings;
