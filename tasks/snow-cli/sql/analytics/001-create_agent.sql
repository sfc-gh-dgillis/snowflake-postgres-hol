-- ========================================================================
-- 001-create_agent.sql   (Snowflake, step 7)
--
-- A Cortex Agent that answers questions about the mirrored IoT data through
-- the semantic view. Cortex Agents require Enterprise Edition or higher.
-- Try it in Snowsight (the Agents page under AI and ML) or Snowflake Intelligence.
-- See: https://docs.snowflake.com/en/sql-reference/sql/create-agent
--
-- Agents are not a DCM object type, so this runs after the DCM project
-- iot_mirror_analytics has deployed the dynamic table and semantic view. It is
-- dropped with the lab database when iot_mirror_lab is purged.
--
-- If you see "None of the preferred models are authorized or available in
-- your region", enable cross-region inference (data stays in your region):
--   ALTER ACCOUNT SET CORTEX_ENABLED_CROSS_REGION = 'ANY_REGION';
-- ========================================================================

USE ROLE <% ctx.env.MIRROR_ADMIN_ROLE_NAME %>;
USE WAREHOUSE <% ctx.env.DEMO_WAREHOUSE_NAME %>;
USE DATABASE <% ctx.env.DEMO_DATABASE_NAME %>;
USE SCHEMA <% ctx.env.DEMO_SCHEMA_NAME %>;

CREATE OR REPLACE AGENT <% ctx.env.DEMO_DATABASE_NAME %>.<% ctx.env.DEMO_SCHEMA_NAME %>.<% ctx.env.DEMO_AGENT_NAME %>
    COMMENT = 'Answers questions about IoT data mirrored from Snowflake Postgres'
    PROFILE = '{"display_name": "IoT Mirror Agent", "color": "blue"}'
    FROM SPECIFICATION
    $$
    models:
      orchestration: auto

    orchestration:
      budget:
        seconds: 60
        tokens: 32000

    instructions:
      response: "Provide clear, concise answers with relevant numbers. Round averages to two decimals."
      orchestration: "Use the IoTAnalyst tool for every question about devices, sensors, sites, and readings."
      system: |
        You are an IoT operations assistant. The data is mirrored continuously from an
        operational Snowflake Postgres database into Snowflake.

        Key entities:
        - DEVICES: IoT gateways with a SITE_LOCATION (e.g. Warehouse-A, Loading-Dock,
          Emergency-Bay) and a STATUS (e.g. active, maintenance)
        - SENSORS: two per device, SENSOR_TYPE Temperature (Celsius) or Humidity (Percent)
        - READINGS: time-series VALUE per sensor, with timestamp TS
      sample_questions:
        - question: "Which site had the highest average temperature in the last 12 hours?"
          answer: "I'll average Temperature readings by site over the last 12 hours."
        - question: "How many readings did each sensor type record today?"
          answer: "I'll count readings by sensor type for today's date."
        - question: "Which devices are not active?"
          answer: "I'll list devices whose status is not active."

    tools:
      - tool_spec:
          type: "cortex_analyst_text_to_sql"
          name: "IoTAnalyst"
          description: "Converts questions about IoT devices, sensors, and readings into SQL over the mirrored tables"

    tool_resources:
      IoTAnalyst:
        semantic_view: "<% ctx.env.DEMO_DATABASE_NAME %>.<% ctx.env.DEMO_SCHEMA_NAME %>.<% ctx.env.DEMO_SEMANTIC_VIEW_NAME %>"
        execution_environment:
          type: warehouse
          warehouse: "<% ctx.env.DEMO_WAREHOUSE_NAME %>"
    $$;

SHOW AGENTS LIKE '<% ctx.env.DEMO_AGENT_NAME %>' IN SCHEMA <% ctx.env.DEMO_DATABASE_NAME %>.<% ctx.env.DEMO_SCHEMA_NAME %>;
