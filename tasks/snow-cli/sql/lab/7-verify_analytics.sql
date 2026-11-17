-- ========================================================================
-- Step 7 - Verify the analytics layer   (Snowflake)
--
-- Query the analytics layer built on the mirror.
-- ========================================================================

USE ROLE <% ctx.env.MIRROR_ADMIN_ROLE_NAME %>;
USE WAREHOUSE <% ctx.env.DEMO_WAREHOUSE_NAME %>;
USE DATABASE <% ctx.env.DEMO_DATABASE_NAME %>;
USE SCHEMA <% ctx.env.DEMO_SCHEMA_NAME %>;

-- Dynamic table: the latest hours per site and sensor type
SELECT SITE_LOCATION, SENSOR_TYPE, READING_HOUR, READING_COUNT,
       ROUND(AVG_VALUE, 2) AS AVG_VALUE, MIN_VALUE, MAX_VALUE
FROM <% ctx.env.DEMO_DYNAMIC_TABLE_NAME %>
ORDER BY READING_HOUR DESC, SITE_LOCATION, SENSOR_TYPE
LIMIT 12;

-- Semantic view: average value and reading count per site and sensor type
SELECT *
FROM SEMANTIC_VIEW(
    <% ctx.env.DEMO_SEMANTIC_VIEW_NAME %>
    DIMENSIONS DEVICES.SITE_LOCATION, SENSORS.SENSOR_TYPE
    METRICS READINGS.AVG_VALUE, READINGS.READING_COUNT
)
ORDER BY SITE_LOCATION, SENSOR_TYPE;
