-- ========================================================================
-- Lab 3 - Schema changes   (Postgres)
--
-- Postgres Mirror supports schema evolution: DDL on the source propagates
-- to the Snowflake target without reconfiguring the mirror.
--
-- Tables tracked by snowflake_cdc don't allow ADD COLUMN with a DEFAULT
-- clause, so add the column first, then populate existing rows.
-- Note: a column DDL starts a fresh DEVICES$changes feed in Snowflake.
-- ========================================================================

SET search_path TO :"pg_schema";

-- Add a column
ALTER TABLE devices ADD COLUMN IF NOT EXISTS status TEXT;
UPDATE devices SET status = 'active' WHERE status IS NULL;

-- Rename a column (skipped if a previous run already renamed it)
SELECT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = :'pg_schema' AND table_name = 'devices' AND column_name = 'location'
) AS has_location \gset

\if :has_location
ALTER TABLE devices RENAME COLUMN location TO site_location;
\else
\echo 'devices.location was already renamed to site_location - skipping'
\endif

\d devices
SELECT * FROM devices ORDER BY device_id;
