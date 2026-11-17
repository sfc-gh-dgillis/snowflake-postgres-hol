-- A semantic layer over the mirrored tables: business-friendly dimensions and metrics
-- that Cortex Analyst (and the step 7 agent) turn into SQL. Because it reads the target
-- tables, answers are as fresh as the mirror. Uses SITE_LOCATION and STATUS, so run
-- step 3 (schema changes) first.
-- See: https://docs.snowflake.com/en/sql-reference/sql/create-semantic-view

DEFINE SEMANTIC VIEW {{ lab_database }}.{{ lab_schema }}.{{ semantic_view }}
    TABLES (
        DEVICES AS {{ mirror_database }}.{{ mirror_schema }}.DEVICES
            PRIMARY KEY (DEVICE_ID)
            COMMENT = 'IoT gateways, mirrored from Snowflake Postgres',
        SENSORS AS {{ mirror_database }}.{{ mirror_schema }}.SENSORS
            PRIMARY KEY (SENSOR_ID)
            COMMENT = 'Sensors attached to each device (two per device)',
        READINGS AS {{ mirror_database }}.{{ mirror_schema }}.READINGS
            PRIMARY KEY (READING_ID)
            COMMENT = 'Sensor readings, replicated continuously from Postgres'
    )
    RELATIONSHIPS (
        SENSORS_TO_DEVICES AS SENSORS(DEVICE_ID) REFERENCES DEVICES(DEVICE_ID),
        READINGS_TO_SENSORS AS READINGS(SENSOR_ID) REFERENCES SENSORS(SENSOR_ID)
    )
    FACTS (
        READINGS.READING_VALUE AS VALUE COMMENT = 'Measured value: Celsius for Temperature, Percent for Humidity'
    )
    DIMENSIONS (
        DEVICES.DEVICE_NAME AS DEVICE_NAME COMMENT = 'Device (gateway) name, e.g. IoT-Gateway-1',
        DEVICES.SITE_LOCATION AS SITE_LOCATION COMMENT = 'Site where the device is installed, e.g. Warehouse-A or Loading-Dock',
        DEVICES.STATUS AS STATUS COMMENT = 'Device status, e.g. active or maintenance',
        SENSORS.SENSOR_TYPE AS SENSOR_TYPE COMMENT = 'Temperature or Humidity',
        SENSORS.UNIT AS UNIT COMMENT = 'Celsius or Percent',
        READINGS.READING_TS AS TS COMMENT = 'When the reading was taken',
        READINGS.READING_HOUR AS DATE_TRUNC('hour', TS) COMMENT = 'Hour the reading was taken',
        READINGS.READING_DATE AS DATE(TS) COMMENT = 'Date the reading was taken'
    )
    METRICS (
        READINGS.READING_COUNT AS COUNT(READING_ID) COMMENT = 'Number of readings',
        READINGS.AVG_VALUE AS AVG(VALUE) COMMENT = 'Average reading value',
        READINGS.MIN_VALUE AS MIN(VALUE) COMMENT = 'Lowest reading value',
        READINGS.MAX_VALUE AS MAX(VALUE) COMMENT = 'Highest reading value',
        DEVICES.DEVICE_COUNT AS COUNT(DISTINCT DEVICE_ID) COMMENT = 'Number of devices'
    )
    COMMENT = 'IoT readings mirrored continuously from Snowflake Postgres';
