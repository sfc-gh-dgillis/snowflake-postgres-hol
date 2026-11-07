-- ========================================================================
-- 002-seed_data.sql   (Postgres)
--
-- Sample IoT data from the quickstart: 5 devices, 2 sensors per device,
-- and 485 sensor readings spread over the past several hours.
-- Seeds only an empty schema, so re-running demo-up never duplicates rows.
-- ========================================================================

SET search_path TO :"pg_schema";

SELECT NOT EXISTS (SELECT 1 FROM devices) AS needs_seed \gset

\if :needs_seed

-- 5 devices
INSERT INTO devices (device_name, location)
SELECT
    'IoT-Gateway-' || i,
    CASE WHEN i % 2 = 0 THEN 'Warehouse-A' ELSE 'Loading-Dock' END
FROM generate_series(1, 5) AS i;

-- 10 sensors (2 for each device)
INSERT INTO sensors (device_id, sensor_type, unit)
SELECT
    d.device_id,
    s.type,
    CASE WHEN s.type = 'Temperature' THEN 'Celsius' ELSE 'Percent' END
FROM devices d
CROSS JOIN (SELECT unnest(ARRAY['Temperature', 'Humidity']) AS type) AS s;

-- 485 readings
INSERT INTO readings (sensor_id, value, ts)
SELECT
    (sample_id % 10) + 1,                          -- cycles through the 10 sensors
    (random() * 40 + 10)::numeric(10,2),           -- a value between 10 and 50
    NOW() - (sample_id || ' minutes')::interval    -- offsets time into the past
FROM generate_series(1, 485) AS sample_id;

\else
\echo 'Seed data already present - skipping inserts'
\endif
