-- ========================================================================
-- Lab 5 - Changes to watch through $live and $changes   (Postgres)
--
-- Insert one urgent device and update another. Snowflake's DEVICES$live
-- view shows both within ~30 seconds, before the next scheduled apply
-- updates the DEVICES table. In DEVICES$changes the UPDATE appears as a
-- delete/insert pair that shares one transaction id (_XID).
-- (Uses site_location and status, so run lab-3 first.)
-- ========================================================================

SET search_path TO :"pg_schema";

INSERT INTO devices (device_name, site_location, status)
VALUES ('IoT-Gateway-Urgent', 'Emergency-Bay', 'active');

UPDATE devices SET status = 'maintenance' WHERE device_name = 'IoT-Gateway-1';

SELECT * FROM devices ORDER BY device_id;
