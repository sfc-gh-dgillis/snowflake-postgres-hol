-- ========================================================================
-- stream_readings.sql   (Postgres load generator - task stream-readings)
--
-- Every :stream_interval seconds, for :stream_batches batches:
--   * inserts :stream_batch_size readings for random sensors, and
--   * updates the newest existing reading (an UPDATE replicates as a
--     delete/insert pair in READINGS$changes sharing one _XID; the insert
--     half has _IS_UPDATE = TRUE).
--
-- Watch it land in Snowflake while it runs: READINGS$live trails Postgres
-- by ~30 seconds, while READINGS only moves on each refresh interval.
-- Press Ctrl+C to stop early. Don't run steps 2 or 4 while it is running:
-- their checks wait for row counts to match.
-- ========================================================================

SET search_path TO :"pg_schema";

\echo 'Streaming' :stream_batches 'batches of' :stream_batch_size 'readings every' :stream_interval 'seconds (Ctrl+C to stop)'

WITH new_readings AS (
    INSERT INTO readings (sensor_id, value, ts)
    SELECT
        s.sensor_id,
        CASE WHEN s.sensor_type = 'Temperature'
             THEN (20 + random() * 15)::numeric(10,2)
             ELSE (40 + random() * 50)::numeric(10,2) END,
        NOW()
    FROM generate_series(1, :stream_batch_size) AS g
    CROSS JOIN LATERAL (
        SELECT sensor_id, sensor_type
        FROM sensors
        ORDER BY random() + g * 0  -- referencing g picks a new random sensor for every row
        LIMIT 1
    ) AS s
    RETURNING reading_id
),
corrected AS (
    UPDATE readings
    SET value = value + 0.01
    WHERE reading_id = (SELECT MAX(reading_id) FROM readings)
    RETURNING reading_id
)
SELECT
    clock_timestamp()::timestamp(0) AS batch_at,
    (SELECT COUNT(*) FROM new_readings) AS inserted,
    (SELECT COUNT(*) FROM corrected) AS updated
\watch interval=:stream_interval count=:stream_batches
