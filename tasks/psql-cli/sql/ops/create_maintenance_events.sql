-- ========================================================================
-- create_maintenance_events.sql   (Postgres, step 6)
--
-- A brand-new source table. The mirror uses table-level scope
-- (postgres_tables), so new tables are NOT mirrored until you add them with
-- ALTER_MIRROR(add_tables => ...). A schema-level mirror (postgres_schemas)
-- would pick them up automatically.
-- ========================================================================

SET search_path TO :"pg_schema";

CREATE TABLE IF NOT EXISTS maintenance_events (
    event_id SERIAL PRIMARY KEY,
    device_id INT REFERENCES devices(device_id),
    event_type TEXT NOT NULL, -- e.g., 'Calibration', 'Battery-Swap', 'Firmware-Update'
    notes TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);

COMMENT ON TABLE maintenance_events IS 'Created by snowflake-postgres-hol';

-- Seed one event per device (only if the table is empty)
INSERT INTO maintenance_events (device_id, event_type, notes, created_at)
SELECT
    d.device_id,
    (ARRAY['Calibration', 'Battery-Swap', 'Firmware-Update'])[1 + (d.device_id % 3)],
    'Routine maintenance for ' || d.device_name,
    NOW() - (d.device_id || ' hours')::interval
FROM devices d
WHERE NOT EXISTS (SELECT 1 FROM maintenance_events);

SELECT * FROM maintenance_events ORDER BY event_id;
