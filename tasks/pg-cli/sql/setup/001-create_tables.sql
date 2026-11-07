-- ========================================================================
-- 001-create_tables.sql   (Postgres)
--
-- The operational IoT schema from the quickstart: devices, sensors, and
-- readings. Every table has a PRIMARY KEY so that UPDATE and DELETE
-- replicate through the mirror; a table without a primary key is
-- mirrored insert-only.
--
-- Lab tables carry a marker comment. Setup refuses to reuse a same-named
-- table it did not create, and teardown drops only marked tables.
-- ========================================================================

CREATE SCHEMA IF NOT EXISTS :"pg_schema";
SET search_path TO :"pg_schema";

-- psql variables are not expanded inside DO bodies, so pass the schema in a setting
SELECT set_config('lab.pg_schema', :'pg_schema', false) AS lab_schema;

DO $$
DECLARE
    unmarked_tables TEXT;
BEGIN
    SELECT string_agg(c.relname, ', ') INTO unmarked_tables
    FROM pg_class c
    JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname = current_setting('lab.pg_schema')
      AND c.relname IN ('devices', 'sensors', 'readings', 'maintenance_events')
      AND COALESCE(obj_description(c.oid, 'pg_class'), '') <> 'Created by snowflake-postgres-hol';

    IF unmarked_tables IS NOT NULL THEN
        RAISE EXCEPTION 'Table(s) % already exist in schema % and were not created by this lab. Set PG_SCHEMA_NAME to a dedicated schema (for example iot_lab).',
            unmarked_tables, current_setting('lab.pg_schema');
    END IF;
END $$;

CREATE TABLE IF NOT EXISTS devices (
    device_id SERIAL PRIMARY KEY,
    device_name TEXT NOT NULL,
    location TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS sensors (
    sensor_id SERIAL PRIMARY KEY,
    device_id INT REFERENCES devices(device_id),
    sensor_type TEXT NOT NULL, -- e.g., 'Temperature', 'Humidity'
    unit TEXT
);

CREATE TABLE IF NOT EXISTS readings (
    reading_id SERIAL PRIMARY KEY,
    sensor_id INT REFERENCES sensors(sensor_id),
    value NUMERIC(10, 2),
    ts TIMESTAMP DEFAULT NOW()
);

COMMENT ON TABLE devices IS 'Created by snowflake-postgres-hol';
COMMENT ON TABLE sensors IS 'Created by snowflake-postgres-hol';
COMMENT ON TABLE readings IS 'Created by snowflake-postgres-hol';
