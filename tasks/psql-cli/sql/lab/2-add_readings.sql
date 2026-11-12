-- ========================================================================
-- Lab 2 - Add more data   (Postgres)
--
-- Insert 500 additional readings with varied sensor data spread over the
-- last 24 hours, then watch them replicate to Snowflake.
-- ========================================================================

SET search_path TO :"pg_schema";

INSERT INTO readings (sensor_id, value, ts)
SELECT
    s.sensor_id,
    CASE
        WHEN s.sensor_type = 'Temperature' THEN (20 + (random() * 15))::numeric(10,2) -- Temp: 20-35°C
        ELSE (40 + (random() * 50))::numeric(10,2)                                    -- Humidity: 40-90%
    END AS value,
    -- Spreads the data over the last 24 hours
    NOW() - (random() * (24 * 60) * '1 minute'::interval) AS ts
FROM sensors s
CROSS JOIN generate_series(1, 50) -- 10 sensors * 50 iterations = 500 rows
ORDER BY random();

-- 985 on a fresh lab (485 original + 500 new)
SELECT COUNT(*) AS readings_in_postgres FROM readings;
