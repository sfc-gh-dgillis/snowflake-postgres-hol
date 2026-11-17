-- A declarative pipeline on top of the mirror: hourly metrics per site and sensor type,
-- kept fresh automatically. Mirrored target tables have change tracking enabled by
-- CREATE_MIRROR, so the dynamic table can refresh incrementally as the mirror applies
-- Postgres changes.
--
-- End-to-end freshness = mirror refresh_interval + TARGET_LAG.
-- Uses SITE_LOCATION, so run step 3 (schema changes) first.

DEFINE DYNAMIC TABLE {{ lab_database }}.{{ lab_schema }}.{{ dynamic_table }}
    TARGET_LAG = '1 minute'
    WAREHOUSE = {{ warehouse }}
    REFRESH_MODE = AUTO
    COMMENT = 'Hourly sensor metrics per site, built on tables mirrored from Snowflake Postgres'
AS
SELECT
    d.SITE_LOCATION,
    s.SENSOR_TYPE,
    s.UNIT,
    DATE_TRUNC('hour', r.TS) AS READING_HOUR,
    COUNT(*) AS READING_COUNT,
    AVG(r.VALUE) AS AVG_VALUE,
    MIN(r.VALUE) AS MIN_VALUE,
    MAX(r.VALUE) AS MAX_VALUE
FROM {{ mirror_database }}.{{ mirror_schema }}.READINGS r
JOIN {{ mirror_database }}.{{ mirror_schema }}.SENSORS s
    ON s.SENSOR_ID = r.SENSOR_ID
JOIN {{ mirror_database }}.{{ mirror_schema }}.DEVICES d
    ON d.DEVICE_ID = s.DEVICE_ID
GROUP BY d.SITE_LOCATION, s.SENSOR_TYPE, s.UNIT, DATE_TRUNC('hour', r.TS);
