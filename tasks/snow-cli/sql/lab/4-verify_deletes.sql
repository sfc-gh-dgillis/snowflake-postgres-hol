-- ========================================================================
-- Lab 4 - Verify deletes in Snowflake
--
-- The deleted readings are gone from the target table, but READINGS$changes
-- keeps a 7-day record of them. _CHANGE_TYPE is S (initial snapshot),
-- I (insert), or D (delete). An UPDATE arrives as a D/I pair that shares
-- one _XID, with _IS_UPDATE = TRUE on its I half; a D row with no such
-- matching I row is a real delete.
-- ========================================================================

USE ROLE <% ctx.env.MIRROR_ADMIN_ROLE_NAME %>;
USE WAREHOUSE <% ctx.env.DEMO_WAREHOUSE_NAME %>;

SELECT COUNT(*) AS readings_in_snowflake
FROM <% ctx.env.MIRROR_TARGET_DATABASE_NAME %>.<% ctx.env.PG_SCHEMA_NAME %>.READINGS;

SELECT _CHANGE_TYPE, _IS_UPDATE, COUNT(*) AS change_rows
FROM <% ctx.env.MIRROR_TARGET_DATABASE_NAME %>.<% ctx.env.PG_SCHEMA_NAME %>.READINGS$changes
GROUP BY _CHANGE_TYPE, _IS_UPDATE
ORDER BY _CHANGE_TYPE, _IS_UPDATE;

-- Real deletes: D rows that are not the old half of an UPDATE
SELECT COUNT(*) AS deleted_readings
FROM <% ctx.env.MIRROR_TARGET_DATABASE_NAME %>.<% ctx.env.PG_SCHEMA_NAME %>.READINGS$changes d
WHERE d._CHANGE_TYPE = 'D'
  AND NOT EXISTS (
      SELECT 1
      FROM <% ctx.env.MIRROR_TARGET_DATABASE_NAME %>.<% ctx.env.PG_SCHEMA_NAME %>.READINGS$changes i
      WHERE i._CHANGE_TYPE = 'I'
        AND i._IS_UPDATE
        AND i._XID = d._XID
        AND i.READING_ID = d.READING_ID
  );
